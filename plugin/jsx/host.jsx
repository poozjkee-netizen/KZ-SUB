/*
 * host.jsx — ExtendScript-сторона плагина NP SUB (выполняется внутри Premiere).
 *
 * Функции вызываются из панели через CSInterface.evalScript(). Каждая
 * возвращает СТРОКУ-КОД, а не готовый текст: успех (путь/"INSERTED"), либо
 * "ERROR:<CODE>[:detail]" / "BIN:<CODE>[:detail]". Панель (main.js) переводит
 * коды в сообщения через словарь i18n — так в ExtendScript нет захардкоженного
 * русского/казахского текста, и локализация едина.
 *
 * Коды ERROR: NO_SEQUENCE, NO_PRESET, EXPORT_FAILED, SRT_NOT_FOUND,
 *             IMPORT_FAILED, GENERIC:<текст исключения>.
 * Коды BIN:   NOT_FOUND, NO_SEQUENCE, CAPTION_FALSE, CAPTION_ERR:<текст>,
 *             UNSUPPORTED.
 *
 * ВАЖНО: экспорт секвенции требует пресета .epr (Premiere не умеет
 * экспортировать без пресета). Мы ожидаем аудио-пресет в
 * plugin/presets/audio_wav.epr — его нужно один раз сохранить из Media Encoder
 * (Export → формат WAV → Save Preset). Бинарный .epr нельзя сгенерировать кодом.
 */

/**
 * Открывает системный диалог выбора файла .epr и возвращает путь.
 * @returns {string} путь, "CANCEL" при отмене, или "ERROR:GENERIC:..."
 */
function kzsubPickPreset() {
    try {
        // Фильтр по расширению отличается на Win/Mac; File.openDialog сам
        // подберёт подходящее поведение по платформе.
        var f = File.openDialog("Preset (.epr)", "*.epr");
        if (!f) {
            return "CANCEL";
        }
        return f.fsName;
    } catch (e) {
        return "ERROR:GENERIC:" + e.toString();
    }
}

/**
 * Экспортирует аудио активной секвенции во временный WAV.
 * @param {string} presetPath  абсолютный путь к .epr аудио-пресету
 * @returns {string} путь к WAV или "ERROR:<CODE>"
 */
function kzsubExportSequenceAudio(presetPath) {
    try {
        var seq = app.project.activeSequence;
        if (!seq) {
            return "ERROR:NO_SEQUENCE";
        }

        var preset = new File(presetPath);
        if (!preset.exists) {
            return "ERROR:NO_PRESET";
        }

        var outFile = new File(Folder.temp.fsName + "/kzsub_" + Date.now() + ".wav");

        // workAreaType: 0 = вся секвенция (ENCODE_ENTIRE).
        var ENCODE_ENTIRE = 0;
        var ok = seq.exportAsMediaDirect(outFile.fsName, preset.fsName, ENCODE_ENTIRE);

        // exportAsMediaDirect в разных версиях возвращает разное; проверяем файл.
        if (!outFile.exists) {
            return "ERROR:EXPORT_FAILED:" + ok;
        }
        return outFile.fsName;
    } catch (e) {
        return "ERROR:GENERIC:" + e.toString();
    }
}

/**
 * Ищет в корзине проекта импортированный ассет по имени файла.
 * @returns projectItem или null
 */
function kzsubFindImported(bin, fileName) {
    var base = fileName.replace(/\.[^.]+$/, "");  // имя без расширения
    // Идём с конца — свежеимпортированный обычно последний.
    for (var i = bin.children.numItems - 1; i >= 0; i--) {
        var it = bin.children[i];
        if (it && (it.name === fileName || it.name === base)) {
            return it;
        }
    }
    return null;
}

/**
 * Импортирует .srt и пытается положить его на таймлайн активной секвенции.
 *
 * Безопасность прежде всего: субтитры кладутся на СПЕЦИАЛЬНО ДОБАВЛЕННУЮ новую
 * верхнюю видеодорожку через createCaptionTrack (недеструктивно, существующие
 * клипы не сдвигаются). Если не удалось — откатываемся к импорту в корзину.
 *
 * @returns {string}
 *   "INSERTED"       — субтитры добавлены на таймлайн
 *   "BIN:<CODE>"     — ассет в корзине, нужно перетащить вручную (+причина)
 *   "ERROR:<CODE>"   — сбой
 */
function kzsubImportSrt(srtPath) {
    try {
        var srt = new File(srtPath);
        if (!srt.exists) {
            return "ERROR:SRT_NOT_FOUND";
        }

        var root = app.project.rootItem;
        var imported = app.project.importFiles([srt.fsName], 1, root, 0);
        if (!imported) {
            return "ERROR:IMPORT_FAILED";
        }

        var item = kzsubFindImported(root, srt.name);
        if (!item) {
            return "BIN:NOT_FOUND";
        }

        var seq = app.project.activeSequence;
        if (!seq) {
            return "BIN:NO_SEQUENCE";
        }

        // .srt в Premiere — caption-ассет: на обычную видеодорожку через
        // insertClip он НЕ вставляется. Правильный путь — createCaptionTrack
        // (Premiere 15.4+): создаёт дорожку субтитров и кладёт туда captions.
        if (typeof seq.createCaptionTrack === "function") {
            try {
                // (ассет, время начала в секундах)
                var okCap = seq.createCaptionTrack(item, 0);
                if (okCap) {
                    return "INSERTED";
                }
                return "BIN:CAPTION_FALSE";
            } catch (ecap) {
                return "BIN:CAPTION_ERR:" + ecap.toString();
            }
        }

        return "BIN:UNSUPPORTED";
    } catch (e) {
        return "ERROR:GENERIC:" + e.toString();
    }
}
