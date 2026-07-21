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
 * Открывает системный диалог выбора файла .epr и возвращает путь.
 * @returns {string} путь, "CANCEL" при отмене, или "ERROR: ..."
 */
function kzsubPickPreset() {
    try {
        // Фильтр по расширению отличается на Win/Mac; File.openDialog сам
        // подберёт подходящее поведение по платформе.
        var f = File.openDialog("Аудио-пресетті таңдаңыз (.epr)", "*.epr");
        if (!f) {
            return "CANCEL";
        }
        return f.fsName;
    } catch (e) {
        return "ERROR: " + e.toString();
    }
}

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
            return "ERROR: Аудио-пресет табылмады. Панельдегі «Таңдау» " +
                   "батырмасымен .epr пресетін көрсетіңіз (немесе plugin/presets/ " +
                   "ішіне audio_wav.epr қойыңыз).";
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
 * верхнюю видеодорожку через insertClip (недеструктивно, существующие клипы не
 * сдвигаются и не перезаписываются; всё отменяется Cmd+Z). Если добавить
 * дорожку/вставить не удалось — откатываемся к импорту в корзину.
 *
 * @returns {string}
 *   "INSERTED"   — субтитры добавлены на таймлайн
 *   "BIN: ..."   — ассет в корзине, нужно перетащить вручную (+причина)
 *   "ERROR: ..." — сбой
 */
function kzsubImportSrt(srtPath) {
    try {
        var srt = new File(srtPath);
        if (!srt.exists) {
            return "ERROR: Файл субтитров не найден: " + srtPath;
        }

        var root = app.project.rootItem;
        var imported = app.project.importFiles([srt.fsName], 1, root, 0);
        if (!imported) {
            return "ERROR: Не удалось импортировать .srt в проект.";
        }

        var item = kzsubFindImported(root, srt.name);
        if (!item) {
            return "BIN: ассет импортирован, но не найден для вставки.";
        }

        var seq = app.project.activeSequence;
        if (!seq) {
            return "BIN: нет активной секвенции.";
        }

        // Добавляем новую видеодорожку сверху (QE DOM), не трогая существующие.
        var tracksBefore = seq.videoTracks.numTracks;
        try {
            app.enableQE();
            var qeSeq = qe.project.getActiveSequence();
            // addTracks(numV, videoPos, numA, audioPos, numSubmix, submixPos)
            qeSeq.addTracks(1, qeSeq.numVideoTracks, 0, 0, 0, 0);
        } catch (eqe) {
            // QE недоступен/сигнатура иная — не рискуем существующими дорожками.
        }

        var seq2 = app.project.activeSequence;
        if (seq2.videoTracks.numTracks <= tracksBefore) {
            return "BIN: не удалось добавить дорожку — перетащите ассет вручную.";
        }

        var topTrack = seq2.videoTracks[seq2.videoTracks.numTracks - 1];
        try {
            // Вставка в начало пустой новой дорожки (время 0). Недеструктивно.
            topTrack.insertClip(item, 0);
            return "INSERTED";
        } catch (eins) {
            return "BIN: не удалось вставить на дорожку (" + eins.toString() +
                   ") — перетащите ассет вручную.";
        }
    } catch (e) {
        return "ERROR: " + e.toString();
    }
}
