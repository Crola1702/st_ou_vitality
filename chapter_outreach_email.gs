/**
 * Sends the chapter revitalization email to every row of the "Outreach" sheet.
 *
 * Setup:
 *   1. Run `python3 generate_chapter_outreach.py` to produce chapter_outreach.csv
 *      (never commit that file — it contains officer names/emails).
 *   2. Create a Google Sheet. File > Import > Upload chapter_outreach.csv,
 *      "Insert new sheet", then rename that tab to "Outreach".
 *   3. Set RESPONSE_DEADLINE_TEXT below to this round's actual response deadline.
 *   4. (Optional) Upload the chapter guide (the requirements infographic) to
 *      Drive, open it, copy its file ID from the URL, and paste it into
 *      GUIDE_DRIVE_FILE_ID below to attach it to every email.
 *   5. In the Sheet: Extensions > Apps Script, replace the boilerplate with
 *      this file's contents, save.
 *   6. Run sendOutreachEmails() with DRY_RUN = true first, then check
 *      View > Logs (or Executions) to confirm the recipients/subjects look
 *      right before sending anything for real.
 *   7. Set DRY_RUN = false and run again to actually send.
 *
 * Every email is CC'd to the SAC team (SAC_TEAM_CC below) — update that
 * constant if the team roster changes.
 *
 * Re-running is safe: rows that already have a value in "Sent At" are
 * skipped, and rows with no contactable recipients are skipped too (check
 * "Recipient Count" == 0 in the sheet — those chapters need manual outreach,
 * e.g. through the parent Student Branch's other channels).
 *
 * Gmail quota: a consumer Gmail account can send ~100 emails/day; a Google
 * Workspace account ~1500/day. This dataset is around 171 chapter emails
 * (~263 unique recipients across them) — a personal Gmail account will need
 * two days to get through all of them.
 */

var DRY_RUN = true;
var RESPONSE_DEADLINE_TEXT = 'TODO: set this, e.g. "26 de agosto de 2026"';
var GUIDE_DRIVE_FILE_ID = ''; // optional — leave blank to send without an attachment
var SHEET_NAME = 'Outreach';
var SENDER_NAME = 'SAC – Conexiones IEEE Sección Colombia';
var SAC_TEAM_CC = 'Daniel Gomez Pinzon <danielgomezpinzon@ieee.org>, sac@ieee.org.co, cristobal.arroyo@ieee.org';

function sendOutreachEmails() {
  var sheet = SpreadsheetApp.getActiveSpreadsheet().getSheetByName(SHEET_NAME);
  if (!sheet) throw new Error('No sheet named "' + SHEET_NAME + '" found — see setup step 2.');

  var data = sheet.getDataRange().getValues();
  var headers = data[0];
  var col = {};
  headers.forEach(function (h, i) { col[h] = i; });

  var sentCol = col['Sent At'];
  if (sentCol === undefined) {
    sentCol = headers.length;
    sheet.getRange(1, sentCol + 1).setValue('Sent At');
  }

  var attachments = [];
  if (GUIDE_DRIVE_FILE_ID) {
    attachments.push(DriveApp.getFileById(GUIDE_DRIVE_FILE_ID).getBlob());
  }

  var sentCount = 0;
  var skippedCount = 0;

  for (var r = 1; r < data.length; r++) {
    var row = data[r];
    if (row[sentCol]) { skippedCount++; continue; }

    var recipients = String(row[col['All Recipient Emails']] || '').trim();
    if (!recipients) { skippedCount++; continue; }

    var chapterName = row[col['Chapter Name']];
    var society = row[col['Society']];
    var subject = 'Proceso de revitalización – Capítulo ' + society + ' (' + chapterName + ')';
    var htmlBody = buildEmailBody(society);

    if (DRY_RUN) {
      Logger.log('[DRY RUN] To: ' + recipients + '\nCc: ' + SAC_TEAM_CC + '\nSubject: ' + subject);
    } else {
      GmailApp.sendEmail(recipients, subject, stripHtml(htmlBody), {
        htmlBody: htmlBody,
        cc: SAC_TEAM_CC,
        attachments: attachments,
        name: SENDER_NAME,
      });
      sheet.getRange(r + 1, sentCol + 1).setValue(new Date());
    }
    sentCount++;
  }

  Logger.log((DRY_RUN ? '[DRY RUN] ' : '') + 'Processed ' + sentCount + ' chapter(s), skipped ' + skippedCount + ' (already sent or no contactable recipients).');
}

function buildEmailBody(society) {
  return ''
    + '<p>Estimados Presidentes, Officers, Consejeros y miembros del capítulo de ' + society + ' de las Ramas Estudiantiles IEEE,</p>'
    + '<p>Reciban un cordial saludo,</p>'
    + '<p>Desde el SAC–Conexiones de IEEE Sección Colombia nos encontramos adelantando el proceso de revitalización y depuración de los Capítulos de Rama Estudiantil, con el propósito de fortalecer nuestras comunidades técnicas y garantizar el cumplimiento de los lineamientos establecidos en el IEEE MGA Operations Manual.</p>'
    + '<p>Como parte de este proceso, estamos realizando la verificación del estado de cada capítulo con base en los requisitos mínimos de permanencia, entre ellos:</p>'
    + '<ul>'
    + '<li>Contar con un mínimo de 6 miembros IEEE Student Member o Graduate Student Member.</li>'
    + '<li>Haber realizado y reportado al menos dos (2) reuniones o actividades técnicas durante el año.</li>'
    + '<li>Mantener los officers registrados y actualizados en vTools.</li>'
    + '<li>Contar con una estructura organizacional activa y en funcionamiento.</li>'
    + '</ul>'
    + '<p>Hemos identificado que su capítulo presenta información pendiente de validar o requiere actualización de alguno de estos criterios. Por esta razón, solicitamos muy amablemente que respondan este correo a más tardar el día ' + RESPONSE_DEADLINE_TEXT + ', indicando el estado actual de su capítulo y su intención de:</p>'
    + '<ul>'
    + '<li>Continuar con el proceso de fortalecimiento y reactivación del capítulo, o</li>'
    + '<li>Informar si el capítulo no continuará con sus actividades.</li>'
    + '</ul>'
    + '<p>Es importante mencionar que este proceso busca brindar acompañamiento a todas las unidades que deseen continuar activas. Nuestro equipo está dispuesto a apoyarlos mediante asesorías, capacitaciones y orientación para cumplir con los requisitos establecidos.</p>'
    + '<p>No obstante, si no se recibe respuesta dentro del plazo indicado, el capítulo será considerado como sin intención de continuidad, por lo que se iniciará el proceso correspondiente de revisión para su cierre o disolución, conforme a los lineamientos establecidos por IEEE y el plan de depuración de unidades de la IEEE Sección Colombia.</p>'
    + '<p>Agradecemos su atención y compromiso con el fortalecimiento de la comunidad IEEE en Colombia.</p>'
    + '<p>Quedamos atentos a su respuesta y a brindar el acompañamiento necesario para apoyar la continuidad de su capítulo'
    + (GUIDE_DRIVE_FILE_ID ? ', adjuntamos una guía que servirá como apoyo' : '') + '.</p>'
    + '<p>Cordialmente,<br>' + SENDER_NAME + '</p>';
}

function stripHtml(html) {
  return html.replace(/<\/(p|li)>/g, '\n').replace(/<[^>]+>/g, '').trim();
}
