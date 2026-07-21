/*
 * CSInterface.js — МИНИМАЛЬНЫЙ подмножество-шим Adobe CEP.
 *
 * Реализует ровно тот API, что использует панель KZ-SUB:
 *   new CSInterface(), SystemPath.EXTENSION, getSystemPath(), evalScript(),
 *   getOSInformation().
 *
 * Работает поверх штатного моста CEP `window.__adobe_cep__` — так же, как это
 * делает официальная библиотека. Если понадобится полный функционал (события,
 * тема, HostEnvironment), замените этот файл официальным CSInterface.js из
 * https://github.com/Adobe-CEP/CEP-Resources — API-совместимо.
 */

function SystemPath() {}
SystemPath.USER_DATA = "userData";
SystemPath.COMMON_FILES = "commonFiles";
SystemPath.MY_DOCUMENTS = "myDocuments";
SystemPath.APPLICATION = "application";
SystemPath.EXTENSION = "extension";
SystemPath.HOST_APPLICATION = "hostApplication";

function CSInterface() {}

/**
 * Абсолютный путь системной директории (для нас — папка расширения).
 * Повторяет нормализацию путей официальной библиотеки под Win/Mac.
 */
CSInterface.prototype.getSystemPath = function (pathType) {
  var path = decodeURI(window.__adobe_cep__.getSystemPath(pathType));
  var os = this.getOSInformation();
  if (os.indexOf("Windows") >= 0) {
    path = path.replace("file:///", "");
  } else if (os.indexOf("Mac") >= 0) {
    path = path.replace("file://", "");
  }
  return path;
};

/**
 * Выполняет ExtendScript в хосте (Premiere) и возвращает результат в callback.
 */
CSInterface.prototype.evalScript = function (script, callback) {
  if (callback === null || callback === undefined) {
    callback = function () {};
  }
  window.__adobe_cep__.evalScript(script, callback);
};

/** Строка вида "Windows ..." или "Mac OS ..." для нормализации путей. */
CSInterface.prototype.getOSInformation = function () {
  var ua = navigator.userAgent;
  var platform = navigator.platform;
  if (platform.indexOf("Win") >= 0 || ua.indexOf("Windows") >= 0) {
    return "Windows";
  }
  if (platform.indexOf("Mac") >= 0 || ua.indexOf("Macintosh") >= 0) {
    return "Mac OS X";
  }
  return platform;
};

/** Данные о хосте (appName/appVersion) — на случай, если понадобится. */
CSInterface.prototype.getHostEnvironment = function () {
  return JSON.parse(window.__adobe_cep__.getHostEnvironment());
};
