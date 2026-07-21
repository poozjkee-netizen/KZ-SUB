/*
 * host.jsx — ExtendScript-сторона плагина KZ-SUB (выполняется внутри Premiere).
 *
 * Функции вызываются из панели через CSInterface.evalScript(). Каждая
 * возвращает СТРОКУ: либо результат, либо "ERROR: <текст>". Панель разбирает
 * префикс "ERROR:" и показывает пользователю.
 *
 * ВАЖНО: экспорт секвенции требует пресета .epr (Premiere не умеет
 * экспортировать без пресета). Мы ожидаем аудио-пресет в
 * plugin/presets/audio_wav.epr — его нужно один раз сохранить из Media Encoder
 * (Export → формат WAV → Save Preset). Бинарный .epr нельзя сгенерировать кодом.
 */

/**
 * Экспортирует аудио активной секвенции во временный WAV.
 * @param {string} presetPath  абсолютный путь к .epr аудио-пресету
 * @returns {string} путь к WAV или "ERROR: ..."
 */
function kzsubExportSequenceAudio(presetPath) {
    try {
        var seq = app.project.activeSequence;
        if (!seq) {
            return "ERROR: Нет активной секвенции. Откройте секвенцию в Premiere.";
        }

        var preset = new File(presetPath);
        if (!preset.exists) {
            return "ERROR: Не найден аудио-пресет: " + presetPath +
                   " (см. plugin/presets/README).";
        }

        var outFile = new File(Folder.temp.fsName + "/kzsub_" + Date.now() + ".wav");

        // workAreaType: 0 = вся секвенция (ENCODE_ENTIRE).
        var ENCODE_ENTIRE = 0;
        var ok = seq.exportAsMediaDirect(outFile.fsName, preset.fsName, ENCODE_ENTIRE);

        // exportAsMediaDirect в разных версиях возвращает разное; проверяем файл.
        if (!outFile.exists) {
            return "ERROR: Экспорт аудио не удался (" + ok + ").";
        }
        return outFile.fsName;
    } catch (e) {
        return "ERROR: " + e.toString();
    }
}

/**
 * Импортирует .srt в проект (как ассет субтитров).
 * @param {string} srtPath  абсолютный путь к .srt
 * @returns {string} "OK" или "ERROR: ..."
 *
 * Программная вставка готовой caption-дорожки в секвенцию в ExtendScript
 * поддержана ограниченно и нестабильно между версиями Premiere. Поэтому здесь
 * мы надёжно импортируем .srt в бин проекта; пользователь перетаскивает ассет
 * на таймлайн (одно действие). См. docs/ROADMAP.md — автоматизация вставки.
 */
function kzsubImportSrt(srtPath) {
    try {
        var srt = new File(srtPath);
        if (!srt.exists) {
            return "ERROR: Файл субтитров не найден: " + srtPath;
        }
        var suppressUI = 1;
        var imported = app.project.importFiles(
            [srt.fsName], suppressUI, app.project.rootItem, 0
        );
        if (!imported) {
            return "ERROR: Не удалось импортировать .srt в проект.";
        }
        return "OK";
    } catch (e) {
        return "ERROR: " + e.toString();
    }
}
