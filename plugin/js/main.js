/*
 * main.js — логика панели NP SUB (минималистичный UI).
 *
 * Поток: экспорт аудио (ExtendScript) -> загрузка на бэкенд -> .srt ->
 * вставка субтитров в Premiere (createCaptionTrack).
 *
 * Локализация: ВСЕ видимые строки берутся из i18n.js через I18N.t(key).
 * Язык интерфейса выбирается в Настройках (рус/каз), сохраняется в
 * localStorage и восстанавливается при старте. Захардкоженного текста в этой
 * логике нет — только семантические ключи.
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
  var crypto = require("crypto");

  // Стабильный отпечаток устройства (анти-шаринг ключа): хэш от имени машины,
  // пользователя и платформы. Не содержит личных данных в открытом виде.
  function deviceId() {
    var user = "";
    try { user = os.userInfo().username; } catch (e) {}
    var raw = [os.hostname(), user, os.platform(), os.arch()].join("|");
    return crypto.createHash("sha256").update(raw).digest("hex").slice(0, 32);
  }
  var DEVICE_ID = deviceId();

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
    poweredBy: document.getElementById("poweredBy"),
    langWrap: document.querySelector(".lang-wrap"),
    uiLangSelect: document.getElementById("uiLangSelect"),
    // Прогресс
    progress: document.getElementById("progress"),
    progressStage: document.getElementById("progressStage"),
    progressFill: document.getElementById("progressFill"),
    progressPct: document.getElementById("progressPct"),
    // Гейт активации (первый запуск)
    activation: document.getElementById("activation"),
    activationKey: document.getElementById("activationKey"),
    activationBtn: document.getElementById("activationBtn"),
    activationStatus: document.getElementById("activationStatus"),
  };

  // Короткий алиас переводчика.
  function t(key, vars) { return I18N.t(key, vars); }

  // Общее состояние видимости центра: кнопку прячем и на время обработки,
  // и в режиме настроек. Держим флаги, чтобы не конфликтовали.
  var state = { busy: false, settingsOpen: false };

  function refreshRunVisibility() {
    var hide = state.busy || state.settingsOpen;
    els.run.classList.toggle("hidden", hide);
    els.run.disabled = hide;
  }

  // --- Применение локали к статичным элементам DOM ------------------------
  // Проходим по data-i18n / data-i18n-ph / data-i18n-title и подставляем
  // перевод текущего языка. Вызывается при старте и при смене языка.
  function applyLocale() {
    var i, nodes;
    nodes = document.querySelectorAll("[data-i18n]");
    for (i = 0; i < nodes.length; i++) {
      nodes[i].textContent = t(nodes[i].getAttribute("data-i18n"));
    }
    nodes = document.querySelectorAll("[data-i18n-ph]");
    for (i = 0; i < nodes.length; i++) {
      nodes[i].setAttribute("placeholder", t(nodes[i].getAttribute("data-i18n-ph")));
    }
    nodes = document.querySelectorAll("[data-i18n-title]");
    for (i = 0; i < nodes.length; i++) {
      var v = t(nodes[i].getAttribute("data-i18n-title"));
      nodes[i].setAttribute("title", v);
      nodes[i].setAttribute("aria-label", v);
    }
    document.documentElement.setAttribute("lang", I18N.getLocale());
  }

  // --- Цитаты на время обработки (в текущем языке интерфейса) -------------
  var quoteIdx = -1;
  var quoteTimer = null;
  var quotesList = [];

  function nextQuote() {
    if (!quotesList.length) { return; }
    els.quote.classList.add("faded");
    setTimeout(function () {
      quoteIdx = (quoteIdx + 1) % quotesList.length;
      els.quote.textContent = quotesList[quoteIdx];
      els.quote.classList.remove("faded");
    }, 320);
  }

  function startQuotes() {
    quotesList = I18N.raw("quotes") || [];
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

  // --- Прогресс обработки по этапам ---------------------------------------
  // Реальный процент от сервера получить нельзя (Runpod не отдаёт прогресс),
  // поэтому двигаем полосу по «якорям» реальных этапов конвейера, а на долгом
  // распознавании плавно докручиваем к цели (не достигая её), чтобы UI не
  // выглядел зависшим. Подписи этапов берутся из i18n по ключам.
  var PROGRESS_STAGES = {
    prepare:   { pct: 5,   key: "progress.prepare" },
    export:    { pct: 20,  key: "progress.export" },
    upload:    { pct: 40,  key: "progress.upload" },
    recognize: { pct: 70,  key: "progress.recognize" },
    build:     { pct: 90,  key: "progress.build" },
    importing: { pct: 100, key: "progress.import" },
  };

  var progCur = 0, progTarget = 0, progTimer = null;

  function progRender() {
    var v = Math.round(progCur);
    els.progressFill.style.width = progCur.toFixed(1) + "%";
    els.progressPct.textContent = v + "%";
    els.progress.setAttribute("aria-valuenow", v);
  }

  function progTick() {
    var diff = progTarget - progCur;
    if (diff <= 0.15) { return; }
    progCur += Math.max(diff * 0.06, 0.05);
    if (progCur > progTarget) { progCur = progTarget; }
    progRender();
  }

  // Перейти к этапу: поднять цель и сменить подпись (в текущем языке).
  function progStage(name) {
    var s = PROGRESS_STAGES[name];
    if (!s) { return; }
    if (s.pct > progTarget) { progTarget = s.pct; }
    els.progressStage.textContent = t(s.key);
  }

  function startProgress() {
    progCur = 0;
    progTarget = 0;
    els.progress.classList.remove("hidden");
    progStage("prepare");
    progRender();
    progTimer = setInterval(progTick, 60);
  }

  function finishProgress() {
    progTarget = 100;
    progCur = 100;
    progRender();
  }

  function stopProgress() {
    if (progTimer) { clearInterval(progTimer); progTimer = null; }
    els.progress.classList.add("hidden");
  }

  // Подсказки терпения: если ответ идёт дольше обычного — вероятно, сервер
  // (GPU) «просыпается» после простоя. Без этого пользователь решит, что
  // плагин завис, хотя идёт нормальный холодный старт.
  var PATIENCE_NOTES = [
    [20000, "patience.1"],
    [60000, "patience.2"],
    [150000, "patience.3"],
  ];
  var patienceTimers = [];

  function startPatienceNotes() {
    for (var i = 0; i < PATIENCE_NOTES.length; i++) {
      (function (pair) {
        patienceTimers.push(setTimeout(function () {
          setStatus(t(pair[1]));
        }, pair[0]));
      })(PATIENCE_NOTES[i]);
    }
  }

  function stopPatienceNotes() {
    for (var i = 0; i < patienceTimers.length; i++) { clearTimeout(patienceTimers[i]); }
    patienceTimers = [];
  }

  // --- Статус (одна строка, язык — текущий) --------------------------------
  function setStatus(msg, kind) {
    els.status.className = "status" + (kind ? " " + kind : "");
    els.status.textContent = msg || "";
  }

  // --- Восстановление настроек ---
  // Адрес сервера зашит в HTML (прод-шлюз). Сохранённый в прежних версиях
  // localhost игнорируем — иначе панель после обновления ходила бы на
  // несуществующий локальный сервер.
  try {
    var storedUrl = localStorage.getItem("kzsub.apiUrl") || "";
    if (storedUrl &&
        storedUrl.indexOf("http://localhost") !== 0 &&
        storedUrl.indexOf("http://127.0.0.1") !== 0) {
      els.apiUrl.value = storedUrl;
    }
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

  // Ошибка с ключом перевода: несём ключ i18n и параметры до места показа,
  // где переводим на текущий язык (а не фиксируем язык в момент броска).
  function ierr(key, vars) {
    var e = new Error(key);
    e.i18nKey = key;
    e.vars = vars || null;
    return e;
  }
  // Ошибка с уже готовым (переведённым) текстом.
  function rerr(msg) {
    var e = new Error(msg);
    e.resolved = true;
    return e;
  }
  // Достать текст для показа из любой ошибки.
  function errText(err) {
    if (err && err.i18nKey) { return t(err.i18nKey, err.vars); }
    if (err && err.resolved) { return err.message; }
    var m = (err && err.message) ? err.message : String(err);
    return m.replace(/^ERROR:\s*/, "");
  }

  // --- Перевод кодов, возвращаемых host.jsx (Premiere) --------------------
  // host.jsx отдаёт машинные коды ("ERROR:NO_SEQUENCE", "BIN:UNSUPPORTED"),
  // а текст живёт в словаре — чтобы в ExtendScript не было русских строк.
  var HOST_ERR = {
    NO_SEQUENCE: "host.noSequence",
    NO_PRESET: "host.noPreset",
    EXPORT_FAILED: "host.exportFailed",
    SRT_NOT_FOUND: "host.srtNotFound",
    IMPORT_FAILED: "host.importFailed",
  };
  var BIN_REASON = {
    NOT_FOUND: "bin.notFound",
    NO_SEQUENCE: "bin.noSequence",
    CAPTION_FALSE: "bin.captionFalse",
    CAPTION_ERR: "bin.captionErr",
    UNSUPPORTED: "bin.unsupported",
  };

  function splitCode(body) {
    var idx = body.indexOf(":");
    return {
      code: idx >= 0 ? body.slice(0, idx) : body,
      detail: idx >= 0 ? body.slice(idx + 1) : "",
    };
  }

  function hostErrToMsg(res) {
    var c = splitCode(String(res).replace(/^ERROR:\s*/, ""));
    if (HOST_ERR[c.code]) { return t(HOST_ERR[c.code]); }
    return t("err.generic", { detail: c.detail || c.code });
  }

  function binReasonToMsg(res) {
    var c = splitCode(String(res).replace(/^BIN:\s*/, ""));
    if (BIN_REASON[c.code]) { return t(BIN_REASON[c.code]); }
    return c.detail || c.code;
  }

  // Занято: прячем кнопку, показываем неоновый спиннер, прогресс и цитаты.
  function setBusy(busy) {
    state.busy = busy;
    els.loader.classList.toggle("hidden", !busy);
    refreshRunVisibility();
    if (busy) {
      setStatus("");
      startProgress();
      startQuotes();
      startPatienceNotes();
    } else {
      stopProgress();
      stopQuotes();
      stopPatienceNotes();
    }
  }

  // Режим настроек: чистый экран — только язык интерфейса и поле ключа, внизу
  // «powered by danik np». Прячем кнопку «Создать субтитры», выбор языка
  // субтитров (в шапке) и остаточный статус. Шестерёнка остаётся на месте.
  function toggleSettings() {
    state.settingsOpen = !state.settingsOpen;
    els.settingsPanel.classList.toggle("hidden", !state.settingsOpen);
    els.poweredBy.classList.toggle("hidden", !state.settingsOpen);
    els.langWrap.classList.toggle("hidden", state.settingsOpen);
    if (state.settingsOpen) { setStatus(""); }
    refreshRunVisibility();
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
            catch (e) { reject(ierr("test.badResponse")); }
          } else {
            reject(new Error("HTTP " + res.statusCode));
          }
        });
      });
      req.setTimeout(HEALTH_TIMEOUT_MS, function () { req.destroy(ierr("err.timeout")); });
      req.on("error", reject);
      req.end();
    });
  }

  // Проверка лицензии по ключу (GET /license). Резолвит состояние лицензии
  // {active, status, type, remaining_minutes}; реджектит ierr при 401/сети.
  function checkLicense(apiUrl, apiKey) {
    return new Promise(function (resolve, reject) {
      var u = parseUrl(apiUrl, "/license");
      var opts = u.options;
      opts.method = "GET";
      opts.headers = { "X-API-Key": apiKey };
      var req = u.lib.request(opts, function (res) {
        var chunks = [];
        res.on("data", function (c) { chunks.push(c); });
        res.on("end", function () {
          var text = Buffer.concat(chunks).toString("utf8");
          if (res.statusCode >= 200 && res.statusCode < 300) {
            try { resolve(JSON.parse(text)); }
            catch (e) { reject(ierr("test.badResponse")); }
          } else if (res.statusCode === 401) {
            reject(ierr("test.keyInvalid"));
          } else {
            reject(ierr("err.server", { code: res.statusCode }));
          }
        });
      });
      req.setTimeout(HEALTH_TIMEOUT_MS, function () { req.destroy(ierr("err.timeout")); });
      req.on("error", function () { reject(ierr("err.noConnection")); });
      req.end();
    });
  }

  // Сообщение по статусу неактивной лицензии.
  function licenseStateMsg(status) {
    if (status === "expired") { return t("test.keyExpired"); }
    if (status === "exhausted") { return t("test.keyExhausted"); }
    if (status === "suspended" || status === "revoked") { return t("test.keySuspended"); }
    return t("test.keyInvalid");
  }

  // Показать результат проверки лицензии в заданный сеттер статуса.
  function applyLicenseInfo(info, setOk, setErr) {
    if (info.active) {
      var rem = info.remaining_minutes;
      if (rem === null || rem === undefined) {
        setOk(t("test.keyValidUnlimited"));
      } else {
        setOk(t("test.keyValid", { minutes: Math.floor(rem) }));
      }
      return true;
    }
    setErr(licenseStateMsg(info.status));
    return false;
  }

  function uploadForSrt(apiUrl, apiKey, filePath, onSent) {
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
        "X-Device-Id": DEVICE_ID,
      };

      var req = u.lib.request(opts, function (res) {
        var chunks = [];
        res.on("data", function (c) { chunks.push(c); });
        res.on("end", function () {
          var text = Buffer.concat(chunks).toString("utf8");
          if (res.statusCode >= 200 && res.statusCode < 300) {
            resolve(text);
          } else if (res.statusCode === 401) {
            reject(ierr("err.key401"));
          } else if (res.statusCode === 402) {
            reject(ierr("err.quota402"));
          } else if (res.statusCode === 403) {
            reject(ierr("err.device403"));
          } else if (res.statusCode === 413) {
            reject(ierr("err.tooLong413"));
          } else {
            reject(ierr("err.server", { code: res.statusCode }));
          }
        });
      });
      req.setTimeout(UPLOAD_TIMEOUT_MS, function () {
        req.destroy(ierr("err.noResponse"));
      });
      req.on("error", function () {
        reject(ierr("err.noConnection"));
      });
      // 'finish' — тело запроса ушло в сокет: файл отправлен, дальше сервер
      // распознаёт речь. Реальный «якорь» перехода прогресса на распознавание.
      req.on("finish", function () { if (onSent) { onSent(); } });
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
    var apiKey = els.apiKey.value.trim();
    if (!apiUrl) {
      return setStatus(t("test.noUrl"), "error");
    }
    if (!apiKey) {
      return setStatus(t("activation.enterKey"), "error");
    }
    saveSettings();
    els.test.disabled = true;
    setStatus(t("test.checking"));
    checkLicense(apiUrl, apiKey)
      .then(function (info) {
        applyLicenseInfo(
          info,
          function (m) { setStatus(m, "ok"); },
          function (m) { setStatus(m, "error"); }
        );
      })
      .catch(function (err) {
        setStatus(errText(err), "error");
      })
      .then(function () { els.test.disabled = false; });
  }

  function onPickPreset() {
    els.pickPreset.disabled = true;
    evalScript("kzsubPickPreset()")
      .then(function (res) {
        if (res === "CANCEL" || !res) { return; }
        if (res.indexOf("ERROR:") === 0) {
          return setStatus(hostErrToMsg(res), "error");
        }
        els.presetPath.value = res;
        saveSettings();
        setStatus(t("preset.saved"), "ok");
      })
      .then(function () { els.pickPreset.disabled = false; });
  }

  function runPipeline() {
    var apiUrl = els.apiUrl.value.trim();
    var apiKey = els.apiKey.value.trim();

    if (!apiKey) {
      // Ключа нет — открываем гейт активации (без ключа работа невозможна).
      showActivation();
      return;
    }
    if (!apiUrl) {
      return setStatus(t("err.config"), "error");
    }
    saveSettings();
    setBusy(true);

    var presetPath = resolvePresetPath();

    progStage("export");
    evalScript('kzsubExportSequenceAudio("' + esc(presetPath) + '")')
      .then(function (wavPath) {
        if (!wavPath || wavPath.indexOf("ERROR:") === 0) {
          throw rerr(wavPath ? hostErrToMsg(wavPath) : t("err.export"));
        }
        progStage("upload");
        return uploadForSrt(apiUrl, apiKey, wavPath, function () {
          progStage("recognize");
        }).then(function (srt) {
          return { srt: srt, wavPath: wavPath };
        });
      })
      .then(function (r) {
        progStage("build");
        var srtPath = path.join(os.tmpdir(), "kzsub_" + Date.now() + ".srt");
        fs.writeFileSync(srtPath, r.srt, "utf8");
        progStage("importing");
        return evalScript('kzsubImportSrt("' + esc(srtPath) + '")').then(function (res) {
          try { fs.unlinkSync(r.wavPath); } catch (e) {}
          if (res && res.indexOf("ERROR:") === 0) { throw rerr(hostErrToMsg(res)); }
          return res;
        });
      })
      .then(function (res) {
        finishProgress();
        if (res === "INSERTED") {
          setStatus(t("result.inserted"), "ok");
        } else {
          setStatus(t("result.bin", { reason: binReasonToMsg(res) }), "ok");
        }
      })
      .catch(function (err) {
        setStatus(errText(err), "error");
      })
      .then(function () { setBusy(false); });
  }

  // --- Гейт активации (первый запуск) ------------------------------------
  // Пока ключ не введён и не сохранён — основной интерфейс недоступен (экран
  // активации перекрывает всё). После сохранения ключа гейт больше не
  // показывается; сменить ключ можно только через Настройки.
  function isActivated() {
    try { return !!(localStorage.getItem("kzsub.apiKey") || "").trim(); }
    catch (e) { return false; }
  }

  function showActivation() {
    els.activationKey.value = els.apiKey.value || "";
    els.activation.classList.remove("hidden");
    setTimeout(function () { try { els.activationKey.focus(); } catch (e) {} }, 50);
  }

  function hideActivation() {
    els.activation.classList.add("hidden");
  }

  function setActStatus(msg, isErr) {
    els.activationStatus.textContent = msg || "";
    els.activationStatus.className = "activation-status" + (isErr ? " error" : "");
  }

  function activate() {
    var key = els.activationKey.value.trim();
    if (!key) {
      return setActStatus(t("activation.enterKey"), true);
    }
    var apiUrl = els.apiUrl.value.trim();
    els.activationBtn.disabled = true;
    setActStatus(t("test.checking"));
    // Проверяем ключ на сервере ДО входа: неверный/заблокированный/просроченный
    // ключ не пускает в интерфейс (раньше пускал, а ошибка всплывала только при
    // создании субтитров). При сетевой ошибке тоже не входим — просим повторить.
    checkLicense(apiUrl, key)
      .then(function (info) {
        var ok = applyLicenseInfo(
          info,
          function () {
            els.apiKey.value = key;
            saveSettings();
            hideActivation();
            setStatus(t("welcome"), "ok");
          },
          function (m) { setActStatus(m, true); }
        );
        return ok;
      })
      .catch(function (err) {
        setActStatus(errText(err), true);
      })
      .then(function () { els.activationBtn.disabled = false; });
  }

  // --- Смена языка интерфейса --------------------------------------------
  function onUiLangChange() {
    var code = els.uiLangSelect.value;
    I18N.setLocale(code);
    try { localStorage.setItem("kzsub.uiLang", I18N.getLocale()); } catch (e) {}
    applyLocale();
    setActStatus("");
    setStatus(""); // убрать строку статуса на старом языке
  }

  // --- Инициализация ------------------------------------------------------
  // Восстанавливаем язык интерфейса и применяем его до показа любого текста.
  (function initLocale() {
    var saved = "";
    try { saved = localStorage.getItem("kzsub.uiLang") || ""; } catch (e) {}
    if (saved && I18N.has(saved)) { I18N.setLocale(saved); }
    els.uiLangSelect.value = I18N.getLocale();
    applyLocale();
  })();

  els.run.addEventListener("click", runPipeline);
  els.test.addEventListener("click", onTest);
  els.pickPreset.addEventListener("click", onPickPreset);
  els.settingsToggle.addEventListener("click", toggleSettings);
  els.apiKey.addEventListener("change", saveSettings); // ключ сохраняется сразу
  els.uiLangSelect.addEventListener("change", onUiLangChange);
  els.activationBtn.addEventListener("click", activate);
  els.activationKey.addEventListener("keydown", function (e) {
    if (e.keyCode === 13) { activate(); } // Enter — активировать
  });

  // Первый запуск: нет сохранённого ключа → показываем экран активации.
  if (!isActivated()) {
    showActivation();
  }
})();
