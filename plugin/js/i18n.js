/*
 * i18n.js — единый источник переводов интерфейса NP SUB.
 *
 * Вся видимая пользователю строка живёт ЗДЕСЬ, в словаре STRINGS, и берётся
 * через I18N.t(key[, vars]). Ни в main.js, ни в index.html, ни в host.jsx не
 * должно быть захардкоженного русского/казахского текста.
 *
 * Добавить новый язык (например английский) = добавить блок "en" в STRINGS
 * и пункт в выпадашку «Язык интерфейса». Логику приложения менять НЕ нужно.
 *
 * Подстановка: t("test.ready", { model: "large-v3" }) заменит {model}.
 * Массивы (цитаты) берутся через I18N.raw(key).
 *
 * ES5-совместимо (старый CEF-движок CEP): только var/function, без стрелок.
 */
var I18N = (function () {
  "use strict";

  // Язык по умолчанию при самом первом запуске (до выбора пользователем).
  // Русский как наиболее читаемый в целевом рынке; экран активации показывается
  // до доступа к настройкам, поэтому дефолт должен быть понятен большинству.
  // Пользователь один раз переключит на казахский — выбор сохранится.
  var DEFAULT_LOCALE = "ru";

  var STRINGS = {
    ru: {
      // Шапка: язык субтитров (не интерфейса)
      "lang.contentTitle": "Язык субтитров",
      "lang.kazakh": "Казахский",
      "lang.soon": "Скоро · Кыргызский, Узбекский",

      // Настройки
      "settings.uiLangLabel": "Язык интерфейса",
      "settings.keyLabel": "Ключ активации",
      "settings.keyPlaceholder": "Введите ключ",
      "settings.testBtn": "Проверить",
      "settings.keyHint": "Сменить ключ можно здесь",

      // Главная кнопка
      "run.label": "СОЗДАТЬ СУБТИТРЫ",

      // Экран активации
      "activation.title": "Введите ключ активации",
      "activation.sub": "Добро пожаловать в NP SUB",
      "activation.placeholder": "Лицензионный ключ",
      "activation.btn": "АКТИВИРОВАТЬ",
      "activation.hint": "Нет ключа? Напишите в поддержку",
      "activation.enterKey": "Введите ключ",

      "welcome": "Добро пожаловать! Готово к работе.",

      // Прогресс обработки
      "progress.prepare": "Подготовка проекта…",
      "progress.export": "Экспорт аудио…",
      "progress.upload": "Загрузка файла…",
      "progress.recognize": "Распознавание речи…",
      "progress.build": "Создание субтитров…",
      "progress.import": "Импорт в Premiere…",

      // Подсказки терпения (долгий холодный старт GPU)
      "patience.1": "Сервер запускается, подождите немного…",
      "patience.2": "В первый раз может занять чуть дольше…",
      "patience.3": "Всё ещё работает, не отменяйте сейчас…",

      // Результаты
      "result.inserted": "Готово! Субтитры на таймлайне.",
      "result.bin": "Субтитры импортированы в проект — перетащите на таймлайн.\n({reason})",

      // Проверка сервера (кнопка «Проверить»)
      "test.noUrl": "Укажите адрес сервера.",
      "test.checking": "Проверка…",
      "test.noConnection": "Нет соединения: {detail}",
      "test.badResponse": "Непонятный ответ сервера",
      "test.keyValid": "Ключ активен · осталось {minutes} мин",
      "test.keyValidUnlimited": "Ключ активен · безлимит",
      "test.keyInvalid": "Неверный ключ. Напишите в поддержку.",
      "test.keyExpired": "Срок ключа истёк. Обновите подписку.",
      "test.keyExhausted": "Лимит минут исчерпан. Обновите подписку.",
      "test.keySuspended": "Ключ заблокирован. Напишите в поддержку.",

      "preset.saved": "Пресет сохранён.",

      // Ошибки сети/сервера
      "err.export": "Ошибка экспорта.",
      "err.config": "Ошибка конфигурации. Переоткройте панель.",
      "err.key401": "Ошибка ключа. Напишите в поддержку.",
      "err.quota402": "Лимит исчерпан. Обновите подписку.",
      "err.device403": "Этот ключ привязан к другому устройству. Напишите в поддержку.",
      "err.tooLong413": "Видео слишком длинное.",
      "err.server": "Ошибка сервера (HTTP {code}).",
      "err.noResponse": "Сервер не отвечает.",
      "err.noConnection": "Нет соединения. Повторите позже.",
      "err.timeout": "Таймаут",
      "err.generic": "Ошибка: {detail}",

      // Ошибки со стороны Premiere (host.jsx возвращает коды)
      "host.noSequence": "Нет активной секвенции. Откройте секвенцию в Premiere.",
      "host.noPreset": "Аудио-пресет не найден. Переустановите плагин.",
      "host.exportFailed": "Не удалось экспортировать аудио.",
      "host.srtNotFound": "Файл субтитров не найден.",
      "host.importFailed": "Не удалось импортировать субтитры.",

      // Причины отката субтитров в корзину проекта
      "bin.notFound": "ассет импортирован, но не найден для вставки",
      "bin.noSequence": "нет активной секвенции",
      "bin.captionFalse": "не удалось создать дорожку — перетащите вручную",
      "bin.captionErr": "ошибка дорожки субтитров — перетащите вручную",
      "bin.unsupported": "ваша версия Premiere не поддерживает авто-вставку (нужен 2021.4+)",

      // Мотивационные цитаты во время обработки
      "quotes": [
        "Искусство правит миром",
        "Красота — в мелочах",
        "Творчество — это смелость",
        "Каждый кадр имеет значение",
        "Великое начинается с малого"
      ]
    },

    kk: {
      "lang.contentTitle": "Субтитр тілі",
      "lang.kazakh": "Қазақша",
      "lang.soon": "Жақын арада · Қырғызша, Өзбекше",

      "settings.uiLangLabel": "Интерфейс тілі",
      "settings.keyLabel": "Активация кілті",
      "settings.keyPlaceholder": "Кілтіңізді енгізіңіз",
      "settings.testBtn": "Тексеру",
      "settings.keyHint": "Кілтті осы жерде ауыстырасыз",

      "run.label": "СУБТИТР ЖАСАУ",

      "activation.title": "Кілтіңізді енгізіңіз",
      "activation.sub": "NP SUB-қа қош келдіңіз",
      "activation.placeholder": "Лицензиялық кілт",
      "activation.btn": "АКТИВТЕНДІРУ",
      "activation.hint": "Кілт жоқ па? Қолдау қызметіне жазыңыз",
      "activation.enterKey": "Кілтіңізді енгізіңіз",

      "welcome": "Қош келдіңіз! Дайынбыз.",

      "progress.prepare": "Жоба дайындалуда…",
      "progress.export": "Аудио экспортталуда…",
      "progress.upload": "Файл жүктелуде…",
      "progress.recognize": "Сөйлеу танылуда…",
      "progress.build": "Субтитрлер жасалуда…",
      "progress.import": "Premiere-ге импорт…",

      "patience.1": "Сервер іске қосылуда, күте тұрыңыз…",
      "patience.2": "Бірінші рет сәл ұзағырақ болуы мүмкін…",
      "patience.3": "Әлі жұмыс істеп жатыр, дәл қазір бас тартпаңыз…",

      "result.inserted": "Дайын! Субтитрлер таймлайнда.",
      "result.bin": "Субтитрлер жобаға импортталды — таймлайнға сүйреңіз.\n({reason})",

      "test.noUrl": "Сервер адресін көрсетіңіз.",
      "test.checking": "Тексерілуде…",
      "test.noConnection": "Байланыс жоқ: {detail}",
      "test.badResponse": "Сервер жауабы түсініксіз",
      "test.keyValid": "Кілт белсенді · {minutes} мин қалды",
      "test.keyValidUnlimited": "Кілт белсенді · шексіз",
      "test.keyInvalid": "Кілт жарамсыз. Қолдау қызметіне жазыңыз.",
      "test.keyExpired": "Кілттің мерзімі бітті. Жазылымды жаңартыңыз.",
      "test.keyExhausted": "Минут лимиті таусылды. Жазылымды жаңартыңыз.",
      "test.keySuspended": "Кілт бұғатталған. Қолдау қызметіне жазыңыз.",

      "preset.saved": "Пресет сақталды.",

      "err.export": "Экспорт сәтсіз аяқталды.",
      "err.config": "Қате конфигурация. Панельді қайта ашыңыз.",
      "err.key401": "Кілт қатесі. Қолдау қызметіне жазыңыз.",
      "err.quota402": "Лимит таусылды. Жазылымды жаңартыңыз.",
      "err.device403": "Бұл кілт басқа құрылғыға тіркелген. Қолдау қызметіне жазыңыз.",
      "err.tooLong413": "Видео тым ұзын.",
      "err.server": "Сервер қатесі (HTTP {code}).",
      "err.noResponse": "Сервер жауап бермеді.",
      "err.noConnection": "Байланыс жоқ. Кейінірек қайталап көріңіз.",
      "err.timeout": "Таймаут",
      "err.generic": "Қате: {detail}",

      "host.noSequence": "Белсенді секвенция жоқ. Premiere-де секвенция ашыңыз.",
      "host.noPreset": "Аудио-пресет табылмады. Плагинді қайта орнатыңыз.",
      "host.exportFailed": "Аудионы экспорттау мүмкін болмады.",
      "host.srtNotFound": "Субтитр файлы табылмады.",
      "host.importFailed": "Субтитрлерді импорттау мүмкін болмады.",

      "bin.notFound": "ассет импортталды, бірақ кірістіру үшін табылмады",
      "bin.noSequence": "белсенді секвенция жоқ",
      "bin.captionFalse": "дорожка жасалмады — қолмен сүйреңіз",
      "bin.captionErr": "субтитр дорожкасының қатесі — қолмен сүйреңіз",
      "bin.unsupported": "Premiere нұсқаңыз авто-кірістіруді қолдамайды (2021.4+ керек)",

      "quotes": [
        "Өнер — өмірдің тынысы",
        "Әр кадр — бір әлем",
        "Шабыт жүректен шығады",
        "Сөз — күміс, субтитр — алтын",
        "Ұлы іс кішіден басталады"
      ]
    }
  };

  var current = DEFAULT_LOCALE;

  function has(code) {
    return !!STRINGS[code];
  }

  function setLocale(code) {
    if (has(code)) { current = code; }
    return current;
  }

  function getLocale() {
    return current;
  }

  // Сырое значение ключа (для массивов вроде цитат). Фолбэк — ru.
  function raw(key) {
    var pack = STRINGS[current] || STRINGS[DEFAULT_LOCALE];
    if (pack && pack[key] !== undefined) { return pack[key]; }
    return STRINGS[DEFAULT_LOCALE][key];
  }

  // Строка ключа с подстановкой {name} из vars.
  function t(key, vars) {
    var val = raw(key);
    if (typeof val !== "string") { return key; } // ключ не найден — показываем сам ключ (заметно при отладке)
    if (!vars) { return val; }
    return val.replace(/\{(\w+)\}/g, function (m, name) {
      return vars[name] !== undefined ? String(vars[name]) : m;
    });
  }

  // Список доступных языков: [{code, name}] — name на самом этом языке (эндоним).
  var NAMES = { ru: "Русский", kk: "Қазақша", en: "English" };
  function locales() {
    var out = [];
    for (var code in STRINGS) {
      if (STRINGS.hasOwnProperty(code)) {
        out.push({ code: code, name: NAMES[code] || code });
      }
    }
    return out;
  }

  return {
    t: t,
    raw: raw,
    has: has,
    setLocale: setLocale,
    getLocale: getLocale,
    locales: locales,
    DEFAULT_LOCALE: DEFAULT_LOCALE
  };
})();
