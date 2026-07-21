/*
 * main.js — логика панели KZ-SUB (минималистичный UI).
 *
 * Поток: экспорт аудио (ExtendScript) -> загрузка на бэкенд -> .srt ->
 * вставка субтитров в Premiere (createCaptionTrack).
 *
 * Во время работы показывается неоновый лоадер (без подписей этапов);
 * текст статуса используется для результата и ошибок.
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

  var UPLOAD_TIMEOUT_MS = 10 * 60 * 1000;
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
    loader: document.getElementById("loader"),
    settingsToggle: document.getElementById("settingsToggle"),
    settingsPanel: document.getElementById("settingsPanel"),
    runLabel: document.getElementById("runLabel"),
    runContent: document.getElementById("runContent"),
    quote: document.getElementById("quote"),
  };

  // --- Надпись кнопки: каз ⇄ рус, смена раз в 5 секунд через затухание.
  //     Затухает весь контент кнопки (иконка вместе с текстом). ---
  var RUN_LABELS = ["СУБТИТР ЖАСАУ", "СОЗДАТЬ СУБТИТРЫ"];
  var runLabelIdx = 0;

  setInterval(function () {
    // Пока кнопка скрыта (идёт обработка) — не крутим.
    if (els.run.classList.contains("hidden")) { return; }
    els.runContent.classList.add("faded");
    setTimeout(function () {
      runLabelIdx = (runLabelIdx + 1) % RUN_LABELS.length;
      els.runLabel.textContent = RUN_LABELS[runLabelIdx];
      els.runContent.classList.remove("faded");
    }, 320); // ждём конца затухания
  }, 5000);

  // --- Цитаты на время обработки: рус и каз по очереди, по кругу ---
  var QUOTES = [
    "Искусство правит миром",
    "Өнер — өмірдің тынысы",            // Искусство — дыхание жизни
    "Красота — в мелочах",
    "Әр кадр — бір әлем",               // Каждый кадр — целый мир
    "Творчество — это смелость",
    "Шабыт жүректен шығады",            // Вдохновение идёт от сердца
    "Каждый кадр имеет значение",
    "Сөз — күміс, субтитр — алтын",     // Слово — серебро, субтитр — золото
    "Великое начинается с малого",
    "Ұлы іс кішіден басталады",         // Великое начинается с малого
  ];
  var quoteIdx = -1;
  var quoteTimer = null;

  function nextQuote() {
    els.quote.classList.add("faded");
    setTimeout(function () {
      quoteIdx = (quoteIdx + 1) % QUOTES.length;
      els.quote.textContent = QUOTES[quoteIdx];
      els.quote.classList.remove("faded");
    }, 320);
  }

  function startQuotes() {
    quoteIdx = -1;
    els.quote.classList.remove("hidden");
    nextQuote();
    quoteTimer = setInterval(nextQuote, 3000);
  }

  function stopQuotes() {
    if (quoteTimer) { clearInterval(quoteTimer); quoteTimer = null; }
    els.quote.classList.add("hidden");
    els.quote.textContent = "";
  }

  // --- Восстановление настроек (дефолты: localhost + dev-key) ---
  try {
    els.apiUrl.value = localStorage.getItem("kzsub.apiUrl") || els.apiUrl.value;
    els.apiKey.value = localStorage.getItem("kzsub.apiKey") || "dev-key";
    els.presetPath.value = localStorage.getItem("kzsub.presetPath") || "";
  } catch (e) {
    els.apiKey.value = els.apiKey.value || "dev-key";
  }

  function saveSettings() {
    try {
      localStorage.setItem("kzsub.apiUrl", els.apiUrl.value.trim());
      localStorage.setItem("kzsub.apiKey", els.apiKey.value.trim());
      localStorage.setItem("kzsub.presetPath", els.presetPath.value.trim());
    } catch (e) {}
  }

  function setStatus(msg, kind) {
    els.status.textContent = msg || "";
    els.status.className = "status" + (kind ? " " + kind : "");
  }

  // Занято: прячем кнопку, показываем неоновый спиннер и цитаты.
  function setBusy(busy) {
    els.run.disabled = busy;
    els.run.classList.toggle("hidden", busy);
    els.loader.classList.toggle("hidden", !busy);
    if (busy) {
      setStatus("");
      startQuotes();
    } else {
      stopQuotes();
    }
  }

  function toggleSettings() {
    els.settingsPanel.classList.toggle("hidden");
  }

  function extensionRoot() {
    return cs.getSystemPath(SystemPath.EXTENSION);
  }

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
            catch (e) { reject(new Error("Сервер жауабы түсініксіз")); }
          } else {
            reject(new Error("HTTP " + res.statusCode));
          }
        });
      });
      req.setTimeout(HEALTH_TIMEOUT_MS, function () { req.destroy(new Error("Таймаут")); });
      req.on("error", reject);
      req.end();
    });
  }

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
            reject(new Error("Кілт қатесі. Қолдау қызметіне жазыңыз."));
          } else if (res.statusCode === 402) {
            reject(new Error("Лимит таусылды. Жазылымды жаңартыңыз."));
          } else if (res.statusCode === 413) {
            reject(new Error("Видео тым ұзын."));
          } else {
            reject(new Error("Сервер қатесі (HTTP " + res.statusCode + ")."));
          }
        });
      });
      req.setTimeout(UPLOAD_TIMEOUT_MS, function () { req.destroy(new Error("Сервер жауап бермеді.")); });
      req.on("error", function (e) {
        reject(new Error("Байланыс жоқ. Кейінірек қайталап көріңіз."));
      });
      req.write(body);
      req.end();
    });
  }

  function resolvePresetPath() {
    var chosen = els.presetPath.value.trim();
    if (chosen) { return chosen; }
    return path.join(extensionRoot(), "presets", "audio_wav.epr");
  }

  function onTest() {
    var apiUrl = els.apiUrl.value.trim();
    if (!apiUrl) { return setStatus("Сервер адресін көрсетіңіз.", "error"); }
    saveSettings();
    els.test.disabled = true;
    setStatus("Тексерілуде…");
    checkHealth(apiUrl)
      .then(function (info) {
        setStatus("Сервер дайын · " + (info.model || "?"), "ok");
      })
      .catch(function (err) {
        setStatus("Байланыс жоқ: " + (err.message || err), "error");
      })
      .then(function () { els.test.disabled = false; });
  }

  function onPickPreset() {
    els.pickPreset.disabled = true;
    evalScript("kzsubPickPreset()")
      .then(function (res) {
        if (res === "CANCEL" || !res) { return; }
        if (res.indexOf("ERROR:") === 0) {
          return setStatus(res.replace(/^ERROR:\s*/, ""), "error");
        }
        els.presetPath.value = res;
        saveSettings();
        setStatus("Пресет сақталды.", "ok");
      })
      .then(function () { els.pickPreset.disabled = false; });
  }

  function runPipeline() {
    var apiUrl = els.apiUrl.value.trim();
    var apiKey = els.apiKey.value.trim();

    if (!apiUrl || !apiKey) {
      return setStatus("Қате конфигурация. Панельді қайта ашыңыз.", "error");
    }
    saveSettings();
    setBusy(true);

    var presetPath = resolvePresetPath();

    evalScript('kzsubExportSequenceAudio("' + esc(presetPath) + '")')
      .then(function (wavPath) {
        if (!wavPath || wavPath.indexOf("ERROR:") === 0) {
          throw new Error(wavPath || "Экспорт сәтсіз.");
        }
        return uploadForSrt(apiUrl, apiKey, wavPath).then(function (srt) {
          return { srt: srt, wavPath: wavPath };
        });
      })
      .then(function (r) {
        var srtPath = path.join(os.tmpdir(), "kzsub_" + Date.now() + ".srt");
        fs.writeFileSync(srtPath, r.srt, "utf8");
        return evalScript('kzsubImportSrt("' + esc(srtPath) + '")').then(function (res) {
          try { fs.unlinkSync(r.wavPath); } catch (e) {}
          if (res && res.indexOf("ERROR:") === 0) { throw new Error(res); }
          return res;
        });
      })
      .then(function (res) {
        if (res === "INSERTED") {
          setStatus("Дайын! Субтитрлер таймлайнда.", "ok");
        } else {
          var why = String(res).replace(/^BIN:\s*/, "");
          setStatus("Субтитрлер жобаға импортталды — таймлайнға сүйреңіз.\n(" + why + ")", "ok");
        }
      })
      .catch(function (err) {
        var msg = (err && err.message) ? err.message : String(err);
        msg = msg.replace(/^ERROR:\s*/, "");
        setStatus(msg, "error");
      })
      .then(function () { setBusy(false); });
  }

  els.run.addEventListener("click", runPipeline);
  els.test.addEventListener("click", onTest);
  els.pickPreset.addEventListener("click", onPickPreset);
  els.settingsToggle.addEventListener("click", toggleSettings);
})();
