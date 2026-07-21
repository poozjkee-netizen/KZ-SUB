/*
 * main.js — логика панели KZ-SUB.
 *
 * Поток: экспорт аудио (ExtendScript) -> загрузка на бэкенд -> .srt ->
 * импорт субтитров обратно в Premiere (ExtendScript).
 *
 * Node.js включён в манифесте (--enable-nodejs), поэтому файлы и HTTP делаем
 * через встроенные модули Node — это надёжнее, чем FormData в CEF.
 */
(function () {
  "use strict";

  var cs = new CSInterface();

  var fs = require("fs");
  var os = require("os");
  var path = require("path");
  var http = require("http");
  var https = require("https");
  var urlmod = require("url");

  var UPLOAD_TIMEOUT_MS = 10 * 60 * 1000; // транскрибация длинного ролика может идти долго
  var HEALTH_TIMEOUT_MS = 8 * 1000;

  var els = {
    apiUrl: document.getElementById("apiUrl"),
    apiKey: document.getElementById("apiKey"),
    presetPath: document.getElementById("presetPath"),
    run: document.getElementById("run"),
    test: document.getElementById("test"),
    pickPreset: document.getElementById("pickPreset"),
    status: document.getElementById("status"),
    quota: document.getElementById("quota"),
  };

  // --- Восстановление настроек (localStorage CEF) ---
  try {
    els.apiUrl.value = localStorage.getItem("kzsub.apiUrl") || els.apiUrl.value;
    els.apiKey.value = localStorage.getItem("kzsub.apiKey") || "";
    els.presetPath.value = localStorage.getItem("kzsub.presetPath") || "";
  } catch (e) {}

  function saveSettings() {
    try {
      localStorage.setItem("kzsub.apiUrl", els.apiUrl.value.trim());
      localStorage.setItem("kzsub.apiKey", els.apiKey.value.trim());
      localStorage.setItem("kzsub.presetPath", els.presetPath.value.trim());
    } catch (e) {}
  }

  function setStatus(msg, kind) {
    els.status.textContent = msg;
    els.status.className = "status" + (kind ? " " + kind : "");
  }

  function extensionRoot() {
    return cs.getSystemPath(SystemPath.EXTENSION);
  }

  // Экранирование пути для передачи строкой в evalScript.
  function esc(p) {
    return String(p).replace(/\\/g, "\\\\").replace(/"/g, '\\"');
  }

  function evalScript(code) {
    return new Promise(function (resolve) {
      cs.evalScript(code, function (res) { resolve(res); });
    });
  }

  function parseUrl(apiUrl, suffix) {
    var parsed = urlmod.parse(apiUrl.replace(/\/+$/, "") + suffix);
    var isHttps = parsed.protocol === "https:";
    return {
      lib: isHttps ? https : http,
      options: {
        hostname: parsed.hostname,
        port: parsed.port || (isHttps ? 443 : 80),
        path: parsed.path,
      },
    };
  }

  // GET /health с таймаутом. Promise<object>.
  function checkHealth(apiUrl) {
    return new Promise(function (resolve, reject) {
      var u = parseUrl(apiUrl, "/health");
      var opts = u.options;
      opts.method = "GET";
      var req = u.lib.request(opts, function (res) {
        var chunks = [];
        res.on("data", function (c) { chunks.push(c); });
        res.on("end", function () {
          var text = Buffer.concat(chunks).toString("utf8");
          if (res.statusCode >= 200 && res.statusCode < 300) {
            try { resolve(JSON.parse(text)); }
            catch (e) { reject(new Error("Некорректный ответ сервера")); }
          } else {
            reject(new Error("HTTP " + res.statusCode));
          }
        });
      });
      req.setTimeout(HEALTH_TIMEOUT_MS, function () { req.destroy(new Error("Таймаут соединения")); });
      req.on("error", reject);
      req.end();
    });
  }

  // Multipart-загрузка файла на /transcribe. Promise<строка SRT>.
  function uploadForSrt(apiUrl, apiKey, filePath) {
    return new Promise(function (resolve, reject) {
      var u = parseUrl(apiUrl, "/transcribe");
      var boundary = "----kzsub" + Date.now().toString(16);
      var fileName = path.basename(filePath);
      var fileData = fs.readFileSync(filePath);

      var head = Buffer.from(
        "--" + boundary + "\r\n" +
        'Content-Disposition: form-data; name="file"; filename="' + fileName + '"\r\n' +
        "Content-Type: audio/wav\r\n\r\n"
      );
      var tail = Buffer.from("\r\n--" + boundary + "--\r\n");
      var body = Buffer.concat([head, fileData, tail]);

      var opts = u.options;
      opts.method = "POST";
      opts.headers = {
        "Content-Type": "multipart/form-data; boundary=" + boundary,
        "Content-Length": body.length,
        "X-API-Key": apiKey,
      };

      var req = u.lib.request(opts, function (res) {
        var chunks = [];
        res.on("data", function (c) { chunks.push(c); });
        res.on("end", function () {
          var text = Buffer.concat(chunks).toString("utf8");
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(text);
          } else if (res.statusCode === 401) {
            reject(new Error("Қате API-кілт (401)."));
          } else if (res.statusCode === 402) {
            reject(new Error("Квота таусылды (402). Жазылымды рәсімдеңіз."));
          } else if (res.statusCode === 413) {
            reject(new Error("Файл тым ұзын (413)."));
          } else {
            reject(new Error("HTTP " + res.statusCode + ": " + text.slice(0, 200)));
          }
        });
      });
      req.setTimeout(UPLOAD_TIMEOUT_MS, function () { req.destroy(new Error("Сервер жауап бермеді (таймаут).")); });
      req.on("error", reject);
      req.write(body);
      req.end();
    });
  }

  function resolvePresetPath() {
    var chosen = els.presetPath.value.trim();
    if (chosen) { return chosen; }
    // Фолбэк: пресет, приложенный к плагину.
    return path.join(extensionRoot(), "presets", "audio_wav.epr");
  }

  // --- Кнопка «Тест» ---
  function onTest() {
    var apiUrl = els.apiUrl.value.trim();
    if (!apiUrl) { return setStatus("API URL көрсетіңіз.", "error"); }
    saveSettings();
    els.test.disabled = true;
    setStatus("Байланыс тексерілуде…");
    checkHealth(apiUrl)
      .then(function (info) {
        setStatus("Сервер жұмыс істеп тұр · модель: " + (info.model || "?") +
                  " · тіл: " + (info.language || "?"), "ok");
      })
      .catch(function (err) {
        setStatus("Байланыс жоқ: " + (err.message || err), "error");
      })
      .then(function () { els.test.disabled = false; });
  }

  // --- Кнопка «Таңдау» (выбор .epr пресета через диалог хоста) ---
  function onPickPreset() {
    els.pickPreset.disabled = true;
    evalScript("kzsubPickPreset()")
      .then(function (res) {
        if (res === "CANCEL" || !res) { return; }
        if (res.indexOf("ERROR:") === 0) {
          return setStatus("Пресетті таңдау қатесі: " + res.replace(/^ERROR:\s*/, ""), "error");
        }
        els.presetPath.value = res;
        saveSettings();
        setStatus("Пресет таңдалды.", "ok");
      })
      .then(function () { els.pickPreset.disabled = false; });
  }

  // --- Основной сценарий ---
  function runPipeline() {
    var apiUrl = els.apiUrl.value.trim();
    var apiKey = els.apiKey.value.trim();

    if (!apiUrl) { return setStatus("API URL көрсетіңіз.", "error"); }
    if (!apiKey) { return setStatus("API-кілт көрсетіңіз.", "error"); }
    saveSettings();

    els.run.disabled = true;
    setStatus("1/3 · Аудио секвенциясын экспорттау…");

    var presetPath = resolvePresetPath();

    evalScript('kzsubExportSequenceAudio("' + esc(presetPath) + '")')
      .then(function (wavPath) {
        if (!wavPath || wavPath.indexOf("ERROR:") === 0) {
          throw new Error(wavPath || "Экспорт бос нәтиже қайтарды.");
        }
        setStatus("2/3 · Қазақша мәтінге айналдыру (сервер)…");
        return uploadForSrt(apiUrl, apiKey, wavPath).then(function (srt) {
          return { srt: srt, wavPath: wavPath };
        });
      })
      .then(function (r) {
        var srtPath = path.join(os.tmpdir(), "kzsub_" + Date.now() + ".srt");
        fs.writeFileSync(srtPath, r.srt, "utf8");
        setStatus("3/3 · Субтитрлерді Premiere-ге импорттау…");
        return evalScript('kzsubImportSrt("' + esc(srtPath) + '")').then(function (res) {
          try { fs.unlinkSync(r.wavPath); } catch (e) {}
          if (res && res.indexOf("ERROR:") === 0) { throw new Error(res); }
          return res;
        });
      })
      .then(function (res) {
        if (res === "INSERTED") {
          setStatus("Дайын! Субтитрлер таймлайнға қосылды (жаңа субтитр-жолақ). " +
                    "Болдырмау — Cmd+Z.", "ok");
        } else {
          // "BIN: ..." — импортировано в корзину, вставить не удалось.
          var why = String(res).replace(/^BIN:\s*/, "");
          setStatus("Субтитр ассеті жобаға импортталды — оны таймлайнға сүйреңіз. (" + why + ")", "ok");
        }
      })
      .catch(function (err) {
        var msg = (err && err.message) ? err.message : String(err);
        msg = msg.replace(/^ERROR:\s*/, "");
        setStatus("Қате: " + msg, "error");
      })
      .then(function () { els.run.disabled = false; });
  }

  els.run.addEventListener("click", runPipeline);
  els.test.addEventListener("click", onTest);
  els.pickPreset.addEventListener("click", onPickPreset);
})();
