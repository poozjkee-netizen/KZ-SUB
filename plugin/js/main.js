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

  var els = {
    apiUrl: document.getElementById("apiUrl"),
    apiKey: document.getElementById("apiKey"),
    run: document.getElementById("run"),
    status: document.getElementById("status"),
    quota: document.getElementById("quota"),
  };

  // --- Сохранение настроек между сессиями (localStorage CEF) ---
  try {
    els.apiUrl.value = localStorage.getItem("kzsub.apiUrl") || els.apiUrl.value;
    els.apiKey.value = localStorage.getItem("kzsub.apiKey") || "";
  } catch (e) {}

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
      cs.evalScript(code, function (res) {
        resolve(res);
      });
    });
  }

  // Multipart-загрузка файла на /transcribe. Возвращает Promise<строка SRT>.
  function uploadForSrt(apiUrl, apiKey, filePath) {
    return new Promise(function (resolve, reject) {
      var parsed = urlmod.parse(apiUrl.replace(/\/+$/, "") + "/transcribe");
      var isHttps = parsed.protocol === "https:";
      var lib = isHttps ? https : http;

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

      var options = {
        hostname: parsed.hostname,
        port: parsed.port || (isHttps ? 443 : 80),
        path: parsed.path,
        method: "POST",
        headers: {
          "Content-Type": "multipart/form-data; boundary=" + boundary,
          "Content-Length": body.length,
          "X-API-Key": apiKey,
        },
      };

      var req = lib.request(options, function (res) {
        var chunks = [];
        res.on("data", function (c) { chunks.push(c); });
        res.on("end", function () {
          var text = Buffer.concat(chunks).toString("utf8");
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(text);
          } else {
            reject(new Error("HTTP " + res.statusCode + ": " + text));
          }
        });
      });
      req.on("error", reject);
      req.write(body);
      req.end();
    });
  }

  function runPipeline() {
    var apiUrl = els.apiUrl.value.trim();
    var apiKey = els.apiKey.value.trim();

    if (!apiUrl) { return setStatus("Укажите API URL.", "error"); }
    if (!apiKey) { return setStatus("Укажите API-кілт (ключ).", "error"); }

    try {
      localStorage.setItem("kzsub.apiUrl", apiUrl);
      localStorage.setItem("kzsub.apiKey", apiKey);
    } catch (e) {}

    els.run.disabled = true;
    setStatus("1/3 · Аудио секвенциясын экспорттау…");

    var presetPath = path.join(extensionRoot(), "presets", "audio_wav.epr");

    evalScript('kzsubExportSequenceAudio("' + esc(presetPath) + '")')
      .then(function (wavPath) {
        if (!wavPath || wavPath.indexOf("ERROR:") === 0) {
          throw new Error(wavPath || "Экспорт вернул пустой результат.");
        }
        setStatus("2/3 · Қазақша мәтінге айналдыру (сервер)…");
        return uploadForSrt(apiUrl, apiKey, wavPath).then(function (srt) {
          return { srt: srt, wavPath: wavPath };
        });
      })
      .then(function (r) {
        // Пишем .srt рядом во временную папку и импортируем в проект.
        var srtPath = path.join(os.tmpdir(), "kzsub_" + Date.now() + ".srt");
        fs.writeFileSync(srtPath, r.srt, "utf8");
        setStatus("3/3 · Субтитрлерді Premiere-ге импорттау…");
        return evalScript('kzsubImportSrt("' + esc(srtPath) + '")').then(function (res) {
          // Чистим временный wav.
          try { fs.unlinkSync(r.wavPath); } catch (e) {}
          if (res && res.indexOf("ERROR:") === 0) { throw new Error(res); }
          return true;
        });
      })
      .then(function () {
        setStatus("Дайын! Субтитр ассеті жобаға импортталды — оны таймлайнға сүйреңіз.", "ok");
      })
      .catch(function (err) {
        var msg = (err && err.message) ? err.message : String(err);
        msg = msg.replace(/^ERROR:\s*/, "");
        setStatus("Қате: " + msg, "error");
      })
      .then(function () {
        els.run.disabled = false;
      });
  }

  els.run.addEventListener("click", runPipeline);
})();
