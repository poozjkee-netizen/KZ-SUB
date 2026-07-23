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

  // Общее состояние видимости центра: кнопку прячем и на время обработки,
  // и в режиме настроек. Держим флаги, чтобы не конфликтовали.
  var state = { busy: false, settingsOpen: false };

  function refreshRunVisibility() {
    var hide = state.busy || state.settingsOpen;
    els.run.classList.toggle("hidden", hide);
    els.run.disabled = hide;
  }

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

  // --- Прогресс обработки по этапам ---------------------------------------
  // Реальный процент от сервера получить нельзя (Runpod не отдаёт прогресс),
  // поэтому двигаем полосу по «якорям» реальных этапов конвейера, а на долгом
  // распознавании плавно докручиваем к цели (асимптотически, не достигая её),
  // чтобы UI не выглядел зависшим. Цель этапа — target; текущее значение cur
  // подтягивается к target на каждом тике. Так короткие этапы «долетают»
  // быстро, а длинный этап распознавания живёт, пока не придёт результат.
  var PROGRESS_STAGES = {
    prepare:   { pct: 5,   kk: "Жоба дайындалуда…",   ru: "Подготовка проекта…" },
    export:    { pct: 20,  kk: "Аудио экспортталуда…", ru: "Экспорт аудио…" },
    upload:    { pct: 40,  kk: "Файл жүктелуде…",      ru: "Загрузка файла…" },
    recognize: { pct: 70,  kk: "Сөйлеу танылуда…",     ru: "Распознавание речи…" },
    build:     { pct: 90,  kk: "Субтитрлер жасалуда…", ru: "Создание субтитров…" },
    importing: { pct: 100, kk: "Premiere-ге импорт…",  ru: "Импорт в Premiere…" },
  };

  var progCur = 0, progTarget = 0, progTimer = null;
  var progStageKk = "", progStageRu = "", progStageShown = false, progStageTimer = null;

  function progRender() {
    var v = Math.round(progCur);
    els.progressFill.style.width = progCur.toFixed(1) + "%";
    els.progressPct.textContent = v + "%";
    els.progress.setAttribute("aria-valuenow", v);
  }

  function progTick() {
    var diff = progTarget - progCur;
    if (diff <= 0.15) { return; }
    // Замедляемся у цели: короткие этапы долетают, длинный распознавания
    // подходит к 70% и «зависает» там, пока реальный результат не сдвинет цель.
    progCur += Math.max(diff * 0.06, 0.05);
    if (progCur > progTarget) { progCur = progTarget; }
    progRender();
  }

  function renderProgStage() {
    els.progressStage.textContent = progStageShown ? progStageRu : progStageKk;
  }

  function swapProgStageLang() {
    if (!progStageRu || progStageRu === progStageKk) { return; }
    els.progressStage.classList.add("faded");
    setTimeout(function () {
      progStageShown = !progStageShown;
      renderProgStage();
      els.progressStage.classList.remove("faded");
    }, 320);
  }

  // Перейти к этапу: поднять цель и сменить подпись (каз, затем каз⇄рус по кругу).
  function progStage(name) {
    var s = PROGRESS_STAGES[name];
    if (!s) { return; }
    if (s.pct > progTarget) { progTarget = s.pct; }
    progStageKk = s.kk;
    progStageRu = s.ru;
    progStageShown = false;
    renderProgStage();
  }

  function startProgress() {
    progCur = 0;
    progTarget = 0;
    progStageShown = false;
    els.progress.classList.remove("hidden");
    progStage("prepare");
    progRender();
    progTimer = setInterval(progTick, 60);
    progStageTimer = setInterval(swapProgStageLang, 5000);
  }

  function finishProgress() {
    // Красивое завершение: доводим до 100% перед скрытием.
    progTarget = 100;
    progCur = 100;
    progRender();
  }

  function stopProgress() {
    if (progTimer) { clearInterval(progTimer); progTimer = null; }
    if (progStageTimer) { clearInterval(progStageTimer); progStageTimer = null; }
    els.progress.classList.add("hidden");
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

  // --- Двуязычный статус: kk показывается, через 5с плавно меняется на ru ---
  var SEP = "\u241F"; // невидимый разделитель kk<SEP>ru
  function bi(kk, ru) { return kk + SEP + ru; }           // собрать двуязычную строку
  function biErr(kk, ru) { return new Error(bi(kk, ru)); } // двуязычная ошибка

  var statusTimer = null;
  var statusKind = "";
  var statusKk = "";
  var statusRu = "";
  var statusRuShown = false;

  function renderStatus(text) {
    els.status.textContent = text || "";
    els.status.className = "status" + (statusKind ? " " + statusKind : "");
  }

  // msg может быть двуязычной ("kkru") или обычной; ru — явный перевод.
  function setStatus(msg, kind, ru) {
    if (statusTimer) { clearInterval(statusTimer); statusTimer = null; }
    statusKind = kind || "";
    var parts = String(msg || "").split(SEP);
    statusKk = parts[0] || "";
    statusRu = ru || parts[1] || "";
    statusRuShown = false;
    renderStatus(statusKk);
    if (statusRu && statusRu !== statusKk) {
      statusTimer = setInterval(swapStatusLang, 5000);
    }
  }

  function swapStatusLang() {
    els.status.classList.add("faded");
    setTimeout(function () {
      statusRuShown = !statusRuShown;
      renderStatus(statusRuShown ? statusRu : statusKk);
    }, 320);
  }

  // Подсказки терпения: если ответ идёт дольше обычного — вероятно, сервер
  // (GPU) сейчас «просыпается» после простоя. Без этого пользователь решит,
  // что плагин завис, хотя на деле идёт нормальный холодный старт.
  var PATIENCE_NOTES = [
    [20000, bi("Сервер іске қосылуда, күте тұрыңыз…",
               "Сервер запускается, подождите немного…")],
    [60000, bi("Бірінші рет сәл ұзағырақ болуы мүмкін…",
               "В первый раз может занять чуть дольше…")],
    [150000, bi("Әлі жұмыс істеп жатыр, дәл қазір бас тартпаңыз…",
                "Всё ещё работает, не отменяйте прямо сейчас…")],
  ];
  var patienceTimers = [];

  function startPatienceNotes() {
    PATIENCE_NOTES.forEach(function (pair) {
      patienceTimers.push(setTimeout(function () {
        setStatus(pair[1]);
      }, pair[0]));
    });
  }

  function stopPatienceNotes() {
    patienceTimers.forEach(clearTimeout);
    patienceTimers = [];
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

  // Режим настроек: показываем панель настроек, прячем кнопку «Создать
  // субтитры» и показываем подпись «powered by danik np» внизу.
  function toggleSettings() {
    state.settingsOpen = !state.settingsOpen;
    els.settingsPanel.classList.toggle("hidden", !state.settingsOpen);
    els.poweredBy.classList.toggle("hidden", !state.settingsOpen);
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
            catch (e) { reject(biErr("Сервер жауабы түсініксіз", "Непонятный ответ сервера")); }
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
            reject(biErr("Кілт қатесі. Қолдау қызметіне жазыңыз.",
                         "Ошибка ключа. Напишите в поддержку."));
          } else if (res.statusCode === 402) {
            reject(biErr("Лимит таусылды. Жазылымды жаңартыңыз.",
                         "Лимит исчерпан. Обновите подписку."));
          } else if (res.statusCode === 403) {
            reject(biErr("Бұл кілт басқа құрылғыға тіркелген. Қолдау қызметіне жазыңыз.",
                         "Этот ключ привязан к другому устройству. Напишите в поддержку."));
          } else if (res.statusCode === 413) {
            reject(biErr("Видео тым ұзын.", "Видео слишком длинное."));
          } else {
            reject(biErr("Сервер қатесі (HTTP " + res.statusCode + ").",
                         "Ошибка сервера (HTTP " + res.statusCode + ")."));
          }
        });
      });
      req.setTimeout(UPLOAD_TIMEOUT_MS, function () {
        req.destroy(biErr("Сервер жауап бермеді.", "Сервер не отвечает."));
      });
      req.on("error", function (e) {
        reject(biErr("Байланыс жоқ. Кейінірек қайталап көріңіз.",
                     "Нет соединения. Повторите позже."));
      });
      // 'finish' — тело запроса ушло в сокет: файл отправлен, дальше сервер
      // распознаёт речь. Реальный «якорь» для перехода прогресса на этап
      // распознавания (самый долгий, включая холодный старт GPU).
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
    if (!apiUrl) {
      return setStatus("Сервер адресін көрсетіңіз.", "error", "Укажите адрес сервера.");
    }
    saveSettings();
    els.test.disabled = true;
    setStatus("Тексерілуде…", null, "Проверка…");
    checkHealth(apiUrl)
      .then(function (info) {
        var m = info.model || "?";
        setStatus("Сервер дайын · " + m, "ok", "Сервер готов · " + m);
      })
      .catch(function (err) {
        var p = String(err && err.message ? err.message : err).split(SEP);
        setStatus("Байланыс жоқ: " + p[0], "error", "Нет соединения: " + (p[1] || p[0]));
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
        setStatus("Пресет сақталды.", "ok", "Пресет сохранён.");
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
      return setStatus("Қате конфигурация. Панельді қайта ашыңыз.", "error",
                       "Ошибка конфигурации. Переоткройте панель.");
    }
    saveSettings();
    setBusy(true);

    var presetPath = resolvePresetPath();

    progStage("export");
    evalScript('kzsubExportSequenceAudio("' + esc(presetPath) + '")')
      .then(function (wavPath) {
        if (!wavPath || wavPath.indexOf("ERROR:") === 0) {
          throw new Error(wavPath || bi("Экспорт сәтсіз.", "Ошибка экспорта."));
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
          if (res && res.indexOf("ERROR:") === 0) { throw new Error(res); }
          return res;
        });
      })
      .then(function (res) {
        finishProgress();
        if (res === "INSERTED") {
          setStatus("Дайын! Субтитрлер таймлайнда.", "ok",
                    "Готово! Субтитры на таймлайне.");
        } else {
          var why = String(res).replace(/^BIN:\s*/, "");
          setStatus("Субтитрлер жобаға импортталды — таймлайнға сүйреңіз.\n(" + why + ")", "ok",
                    "Субтитры импортированы в проект — перетащите на таймлайн.\n(" + why + ")");
        }
      })
      .catch(function (err) {
        var msg = (err && err.message) ? err.message : String(err);
        msg = msg.replace(/^ERROR:\s*/, "");
        var p = msg.split(SEP);
        setStatus(p[0], "error", p[1] || "");
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
      return setActStatus("Кілтіңізді енгізіңіз · Введите ключ", true);
    }
    // Сохраняем ключ в основное поле и localStorage — это и есть «активация».
    // Валидность ключа проверяется сервером при первом создании субтитров
    // (неверный ключ вернёт понятную ошибку 401).
    els.apiKey.value = key;
    saveSettings();
    hideActivation();
    setStatus("Қош келдіңіз! Дайынбыз.", "ok", "Добро пожаловать! Готово к работе.");
  }

  els.run.addEventListener("click", runPipeline);
  els.test.addEventListener("click", onTest);
  els.pickPreset.addEventListener("click", onPickPreset);
  els.settingsToggle.addEventListener("click", toggleSettings);
  els.apiKey.addEventListener("change", saveSettings); // ключ сохраняется сразу
  els.activationBtn.addEventListener("click", activate);
  els.activationKey.addEventListener("keydown", function (e) {
    if (e.keyCode === 13) { activate(); } // Enter — активировать
  });

  // Первый запуск: нет сохранённого ключа → показываем экран активации.
  if (!isActivated()) {
    showActivation();
  }
})();
