import { money, odooDate } from "@/lib/format";
import type { CustomerStatement, CustomerStatementLine } from "@/lib/types";

// Carta vertical. El diseño replica el reporte de "Apuntes abiertos" de Odoo:
// documento, fecha de factura, fecha límite, residual y balance acumulado.
const PAGE_WIDTH = 612;
const PAGE_HEIGHT = 792;
const LEFT = 40;
const RIGHT = PAGE_WIDTH - 40;
const BOTTOM = 64;
const ROW_HEIGHT = 20;
const DOCUMENT_X = LEFT + 16;
const DOCUMENT_END = 306;
const INVOICE_BAND = { x: 310, width: 70 };
const RESIDUAL_BAND = { x: 450, width: 62 };
const INVOICE_CENTER = 345;
const DUE_CENTER = 415;
const RESIDUAL_RIGHT = 506;
const BALANCE_RIGHT = RIGHT - 6;

const COLORS = {
  ink: "0.129 0.145 0.161",
  muted: "0.424 0.459 0.490",
  rule: "0.871 0.886 0.902",
  shade: "0.973 0.976 0.980",
  band: "0.933 0.937 0.945",
  danger: "0.839 0.200 0.259",
  brand: "0.467 0.231 0.525",
  caret: "0.004 0.494 0.518",
};

// Anchos AFM de Helvetica y Helvetica-Bold (1/1000 em) para los caracteres
// 32-126. Permiten alinear montos a la derecha y recortar documentos largos.
const HELVETICA_WIDTHS = [
  278, 278, 355, 556, 556, 889, 667, 191, 333, 333, 389, 584, 278, 333, 278, 278,
  556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
  278, 278, 584, 584, 584, 556, 1015,
  667, 667, 722, 722, 667, 611, 778, 722, 278, 500, 667, 556, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611,
  278, 278, 278, 469, 556, 333,
  556, 556, 500, 556, 556, 278, 556, 556, 222, 222, 500, 222, 833, 556, 556, 556, 556, 333, 500, 278, 556, 500, 722, 500, 500, 500,
  334, 260, 334, 584,
];
const HELVETICA_BOLD_WIDTHS = [
  278, 333, 474, 556, 556, 889, 722, 238, 333, 333, 389, 584, 278, 333, 278, 278,
  556, 556, 556, 556, 556, 556, 556, 556, 556, 556,
  333, 333, 584, 584, 584, 611, 975,
  722, 722, 722, 722, 667, 611, 778, 722, 278, 556, 722, 611, 833, 722, 778, 667, 778, 722, 667, 611, 722, 667, 944, 667, 667, 611,
  333, 278, 333, 584, 556, 333,
  556, 611, 556, 611, 556, 333, 611, 611, 278, 278, 556, 278, 889, 611, 611, 611, 611, 389, 556, 333, 611, 556, 778, 556, 556, 500,
  389, 280, 389, 584,
];

function safePdfText(value: string) {
  return value
    .replace(/[“”]/g, '"')
    .replace(/[‘’]/g, "'")
    .replace(/[–—\u2212]/g, "-")
    .replace(/•/g, "-")
    .replace(/…/g, "...")
    .replace(/[\u202F\u2007]/g, " ")
    .replace(/[^\x09\x0A\x0D\x20-\xFF]/g, "?");
}

function pdfString(value: string) {
  return `(${safePdfText(value).replace(/\\/g, "\\\\").replace(/\(/g, "\\(").replace(/\)/g, "\\)").replace(/[\r\n]+/g, " ")})`;
}

function pdfNumber(value: number) {
  return String(Math.round(value * 100) / 100);
}

function textWidth(value: string, size: number, bold = false) {
  const widths = bold ? HELVETICA_BOLD_WIDTHS : HELVETICA_WIDTHS;
  let units = 0;
  for (const char of safePdfText(value)) {
    let code = char.charCodeAt(0);
    if (code > 126) code = char.normalize("NFD").charCodeAt(0);
    units += code >= 32 && code <= 126 ? widths[code - 32] : 556;
  }
  return (units * size) / 1000;
}

function fitText(value: string, maxWidth: number, size: number, bold = false) {
  if (textWidth(value, size, bold) <= maxWidth) return value;
  let cut = value;
  while (cut.length > 1 && textWidth(`${cut}...`, size, bold) > maxWidth) cut = cut.slice(0, -1);
  return `${cut.trimEnd()}...`;
}

function textOp(value: string, x: number, baseline: number, size: number, bold: boolean, color: string) {
  return `${color} rg BT /${bold ? "F2" : "F1"} ${size} Tf ${pdfNumber(x)} ${pdfNumber(baseline)} Td ${pdfString(value)} Tj ET\n`;
}

function pdfDate(value: string) {
  const date = odooDate(value);
  return date ? date.toLocaleDateString("es-MX", { day: "2-digit", month: "2-digit", year: "numeric" }) : "";
}

function documentLabel(line: CustomerStatementLine) {
  const document = line.document || line.label || "Movimiento";
  return line.reference && !document.includes(line.reference) ? `${document} (${line.reference})` : document;
}

function assemblePdf(pages: string[]) {
  const pageObjectNumbers = pages.map((_, index) => 3 + index * 2);
  const fontRegularObject = 3 + pages.length * 2;
  const fontBoldObject = fontRegularObject + 1;
  const objects: string[] = [
    "<< /Type /Catalog /Pages 2 0 R >>",
    `<< /Type /Pages /Kids [${pageObjectNumbers.map((objectNumber) => `${objectNumber} 0 R`).join(" ")}] /Count ${pages.length} >>`,
  ];

  pages.forEach((content, index) => {
    const pageObject = pageObjectNumbers[index];
    const contentObject = pageObject + 1;
    objects.push(`<< /Type /Page /Parent 2 0 R /MediaBox [0 0 ${PAGE_WIDTH} ${PAGE_HEIGHT}] /Resources << /Font << /F1 ${fontRegularObject} 0 R /F2 ${fontBoldObject} 0 R >> >> /Contents ${contentObject} 0 R >>`);
    objects.push(`<< /Length ${content.length} >>\nstream\n${content}endstream`);
  });
  objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica /Encoding /WinAnsiEncoding >>");
  objects.push("<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica-Bold /Encoding /WinAnsiEncoding >>");

  let pdf = "%PDF-1.4\n%\xE2\xE3\xCF\xD3\n";
  const offsets = [0];
  objects.forEach((object, index) => {
    offsets.push(pdf.length);
    pdf += `${index + 1} 0 obj\n${object}\nendobj\n`;
  });
  const xrefOffset = pdf.length;
  pdf += `xref\n0 ${objects.length + 1}\n0000000000 65535 f \n`;
  for (let index = 1; index <= objects.length; index += 1) {
    pdf += `${String(offsets[index]).padStart(10, "0")} 00000 n \n`;
  }
  pdf += `trailer\n<< /Size ${objects.length + 1} /Root 1 0 R >>\nstartxref\n${xrefOffset}\n%%EOF`;

  // Todo el contenido pasó por safePdfText, así que cada carácter cabe en un byte (WinAnsi).
  const bytes = new Uint8Array(pdf.length);
  for (let index = 0; index < pdf.length; index += 1) bytes[index] = pdf.charCodeAt(index) & 0xff;
  return bytes;
}

export function buildStatementPdfBytes(statement: CustomerStatement) {
  const rows = [...statement.lines].sort(
    (a, b) => (a.date || a.due_date).localeCompare(b.date || b.due_date) || a.id - b.id,
  );
  const customerName = statement.customer.name || "Cliente";
  const totalOpen = rows.reduce((sum, row) => sum + row.open_amount, 0);
  const generated = new Date(statement.generated_at * 1000).toLocaleString("es-MX", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });

  const pages: string[] = [];
  let content = "";
  let y = 0;

  const text = (value: string, x: number, baseline: number, size: number, bold = false, color = COLORS.ink) => {
    content += textOp(value, x, baseline, size, bold, color);
  };
  const textRight = (value: string, rightEdge: number, baseline: number, size: number, bold = false, color = COLORS.ink) =>
    text(value, rightEdge - textWidth(value, size, bold), baseline, size, bold, color);
  const textCenter = (value: string, center: number, baseline: number, size: number, bold = false, color = COLORS.ink) =>
    text(value, center - textWidth(value, size, bold) / 2, baseline, size, bold, color);
  const fill = (x: number, bottom: number, width: number, height: number, color: string) => {
    content += `${color} rg ${pdfNumber(x)} ${pdfNumber(bottom)} ${pdfNumber(width)} ${pdfNumber(height)} re f\n`;
  };
  const rule = (yPosition: number, color = COLORS.rule, lineWidth = 0.6) => {
    content += `${color} RG ${lineWidth} w ${LEFT} ${pdfNumber(yPosition)} m ${RIGHT} ${pdfNumber(yPosition)} l S\n`;
  };
  const shadedColumns = (height: number) => {
    fill(INVOICE_BAND.x, y - height, INVOICE_BAND.width, height, COLORS.shade);
    fill(RESIDUAL_BAND.x, y - height, RESIDUAL_BAND.width, height, COLORS.shade);
  };
  const amounts = (residual: number, balance: number, baseline: number, size: number, bold: boolean) => {
    textRight(money(residual), RESIDUAL_RIGHT, baseline, size, bold);
    textRight(money(balance), BALANCE_RIGHT, baseline, size, bold);
  };

  const startPage = (first: boolean) => {
    if (content) pages.push(content);
    content = "";
    y = PAGE_HEIGHT - 48;
    text("RapyVet", LEFT, y, 18, true, COLORS.brand);
    textRight("Estado de cuenta", RIGHT, y, 14, true);
    y -= 16;
    text("Distribuidor veterinario", LEFT, y, 9, false, COLORS.muted);
    textRight(`Generado: ${generated}`, RIGHT, y, 9, false, COLORS.muted);
    y -= 10;
    rule(y, COLORS.brand, 1);
    y -= 26;

    if (first) {
      text("CLIENTE", LEFT, y, 7.5, true, COLORS.muted);
      y -= 15;
      text(fitText(customerName, RIGHT - LEFT, 13, true), LEFT, y, 13, true);
      y -= 17;
      const summary: [string, number, string][] = [
        ["Saldo pendiente", statement.total_due, COLORS.ink],
        ["Vencido", statement.overdue_due, statement.overdue_due > 0 ? COLORS.danger : COLORS.ink],
        ["Saldo a favor", statement.credit_balance, COLORS.ink],
      ];
      let x = LEFT;
      for (const [label, value, color] of summary) {
        const labelText = `${label}: `;
        text(labelText, x, y, 9, false, COLORS.muted);
        x += textWidth(labelText, 9);
        text(money(value), x, y, 9, true, color);
        x += textWidth(money(value), 9, true) + 24;
      }
      y -= 26;
    } else {
      text(`${customerName.toLocaleUpperCase("es-MX")} (continuación)`, LEFT, y, 9, true, COLORS.muted);
      y -= 18;
    }

    const baseline = y - 14;
    textCenter("Fecha de factura", INVOICE_CENTER, baseline, 8.5, true);
    textCenter("Fecha límite", DUE_CENTER, baseline, 8.5, true);
    textRight("Residual", RESIDUAL_RIGHT, baseline, 8.5, true);
    textRight("Balance", BALANCE_RIGHT, baseline, 8.5, true);
    y -= 22;
  };

  startPage(true);

  // Totales generales.
  shadedColumns(24);
  text("Apuntes abiertos", LEFT, y - 15.5, 9.5, true);
  amounts(totalOpen, totalOpen, y - 15.5, 9.5, true);
  y -= 24;

  // Bloque gris del cliente, con la flecha de agrupación del reporte de Odoo.
  fill(LEFT, y - 24, RIGHT - LEFT, 24, COLORS.band);
  rule(y);
  rule(y - 24);
  content += `${COLORS.caret} rg ${LEFT + 4} ${pdfNumber(y - 10)} m ${LEFT + 11} ${pdfNumber(y - 10)} l ${LEFT + 7.5} ${pdfNumber(y - 14.5)} l f\n`;
  text(fitText(customerName.toLocaleUpperCase("es-MX"), DOCUMENT_END - DOCUMENT_X, 9.5, true), DOCUMENT_X, y - 15.5, 9.5, true);
  amounts(totalOpen, totalOpen, y - 15.5, 9.5, true);
  y -= 24;

  if (!rows.length) {
    text("Sin apuntes abiertos. La cuenta está al corriente.", DOCUMENT_X, y - 14, 9, false, COLORS.muted);
    y -= 22;
  }

  let balance = 0;
  for (const row of rows) {
    if (y - ROW_HEIGHT < BOTTOM) startPage(false);
    balance += row.open_amount;
    const baseline = y - 13.5;
    shadedColumns(ROW_HEIGHT);
    text(fitText(documentLabel(row), DOCUMENT_END - DOCUMENT_X, 8.5), DOCUMENT_X, baseline, 8.5);
    textCenter(pdfDate(row.date), INVOICE_CENTER, baseline, 8.5);
    textCenter(pdfDate(row.due_date), DUE_CENTER, baseline, 8.5, false, row.days_overdue > 0 ? COLORS.danger : COLORS.ink);
    amounts(row.open_amount, balance, baseline, 8.5, false);
    y -= ROW_HEIGHT;
    rule(y, COLORS.rule, 0.5);
  }

  text("Documento informativo. Los pagos se registran y aplican únicamente en Odoo.", LEFT, Math.max(y - 22, 48), 8, false, COLORS.muted);
  pages.push(content);

  return assemblePdf(
    pages.map((page, index) => {
      const pageLabel = `Página ${index + 1} de ${pages.length}`;
      return (
        page +
        textOp(fitText(`RapyVet Pedidos · ${customerName}`, 380, 7.5), LEFT, 28, 7.5, false, COLORS.muted) +
        textOp(pageLabel, RIGHT - textWidth(pageLabel, 7.5), 28, 7.5, false, COLORS.muted)
      );
    }),
  );
}

export function downloadStatementPdf(statement: CustomerStatement) {
  const filenameBase = safePdfText(statement.customer.name || "cliente")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 52) || "cliente";
  const blob = new Blob([buildStatementPdfBytes(statement)], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = `estado-cuenta-${filenameBase}.pdf`;
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}
