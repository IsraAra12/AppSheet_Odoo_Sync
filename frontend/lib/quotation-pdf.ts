import { money } from "@/lib/format";
import type { CartLine, Client, OrderResult, Seller } from "@/lib/types";

const PAGE_WIDTH = 612;
const PAGE_HEIGHT = 792;
const LEFT = 42;
const RIGHT = PAGE_WIDTH - 42;
const BOTTOM = 62;
const ROW_HEIGHT = 26;

const COLORS = {
  ink: "0.965 0.949 0.976",
  muted: "0.741 0.686 0.761",
  faint: "0.557 0.486 0.588",
  rule: "0.294 0.164 0.329",
  surface: "0.100 0.119 0.114",
  soft: "0.139 0.098 0.151",
  band: "0.250 0.122 0.292",
  brand: "0.549 0.259 0.600",
  brandBright: "0.973 0.549 0.953",
  success: "0.278 0.780 0.553",
};

// Anchos AFM de Helvetica y Helvetica-Bold (1/1000 em) para caracteres 32-126.
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

export type QuotationPdfLine = CartLine & {
  total: number;
};

export type QuotationPdfData = {
  result: OrderResult;
  customer: Client;
  seller?: Seller;
  lines: QuotationPdfLine[];
  note?: string;
};

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

function textRightOp(value: string, rightEdge: number, baseline: number, size: number, bold: boolean, color: string) {
  return textOp(value, rightEdge - textWidth(value, size, bold), baseline, size, bold, color);
}

function rectOp(x: number, bottom: number, width: number, height: number, color: string) {
  return `${color} rg ${pdfNumber(x)} ${pdfNumber(bottom)} ${pdfNumber(width)} ${pdfNumber(height)} re f\n`;
}

function ruleOp(y: number, color = COLORS.rule, lineWidth = 0.6) {
  return `${color} RG ${lineWidth} w ${LEFT} ${pdfNumber(y)} m ${RIGHT} ${pdfNumber(y)} l S\n`;
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

  const bytes = new Uint8Array(pdf.length);
  for (let index = 0; index < pdf.length; index += 1) bytes[index] = pdf.charCodeAt(index) & 0xff;
  return bytes;
}

function filenameBase(value: string) {
  return safePdfText(value || "cliente")
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")
    .replace(/[^a-zA-Z0-9_-]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 52) || "cliente";
}

function normalizeWhatsAppPhone(phone: string) {
  const digits = (phone || "").replace(/\D/g, "");
  if (!digits) return "";
  if (digits.length === 10) return `52${digits}`;
  if (digits.startsWith("00") && digits.length > 12) return digits.slice(2);
  return digits;
}

export function quotationPdfFilename(data: QuotationPdfData) {
  const folio = filenameBase(data.result.folio || "cotizacion");
  const customer = filenameBase(data.customer.name || "cliente");
  return `cotizacion-${folio}-${customer}.pdf`;
}

export function buildQuotationWhatsAppUrl(message: string, phone?: string) {
  const encoded = encodeURIComponent(message);
  const normalized = normalizeWhatsAppPhone(phone || "");
  return normalized ? `https://wa.me/${normalized}?text=${encoded}` : `https://wa.me/?text=${encoded}`;
}

export function buildQuotationWhatsAppMessage(data: QuotationPdfData) {
  const rows = [
    `Cotización RapyVet ${data.result.folio || `#${data.result.id}`}`,
    `Cliente: ${data.customer.name || "Cliente"}`,
  ];
  if (data.seller?.name) rows.push(`Vendedor: ${data.seller.name}`);
  rows.push(`Total: ${money(data.result.total)}`);
  rows.push("");
  rows.push("Productos:");
  data.lines.forEach((line) => {
    const suffix = line.free ? " (GRATIS)" : "";
    rows.push(`- ${line.quantity} x ${line.name}${suffix}`);
  });
  rows.push("");
  rows.push("Te comparto el PDF de la cotización para revisión.");
  return rows.join("\n");
}

export function buildQuotationPdfBytes(data: QuotationPdfData) {
  const pages: string[] = [];
  const generated = new Date().toLocaleString("es-MX", {
    day: "2-digit",
    month: "2-digit",
    year: "numeric",
    hour: "2-digit",
    minute: "2-digit",
  });
  let content = "";
  let y = PAGE_HEIGHT - 44;

  const text = (value: string, x: number, baseline: number, size: number, bold = false, color = COLORS.ink) => {
    content += textOp(value, x, baseline, size, bold, color);
  };
  const textRight = (value: string, rightEdge: number, baseline: number, size: number, bold = false, color = COLORS.ink) => {
    content += textRightOp(value, rightEdge, baseline, size, bold, color);
  };
  const rect = (x: number, bottom: number, width: number, height: number, color: string) => {
    content += rectOp(x, bottom, width, height, color);
  };
  const rule = (lineY: number, color = COLORS.rule, lineWidth = 0.6) => {
    content += ruleOp(lineY, color, lineWidth);
  };

  const customerContact = [
    data.customer.email,
    data.customer.phone,
    [data.customer.street, data.customer.city, data.customer.postal_code].filter(Boolean).join(", "),
  ].filter(Boolean);

  const startPage = (first: boolean) => {
    if (content) pages.push(content);
    content = "";
    y = PAGE_HEIGHT - 44;
    rect(0, 0, PAGE_WIDTH, PAGE_HEIGHT, "0.055 0.043 0.063");
    text("RapyVet", LEFT, y, 20, true, COLORS.brandBright);
    textRight("Cotización", RIGHT, y, 16, true, COLORS.ink);
    y -= 15;
    text("Distribuidor veterinario", LEFT, y, 8.5, false, COLORS.muted);
    textRight(`Generado: ${generated}`, RIGHT, y, 8.5, false, COLORS.muted);
    y -= 12;
    rule(y, COLORS.brand, 1.1);
    y -= 24;

    if (first) {
      rect(LEFT, y - 74, RIGHT - LEFT, 74, COLORS.soft);
      text("CLIENTE", LEFT + 16, y - 18, 7.5, true, COLORS.brandBright);
      text(fitText(data.customer.name || "Cliente", RIGHT - LEFT - 32, 15, true), LEFT + 16, y - 38, 15, true);
      text(fitText(customerContact.join(" - ") || "Sin datos de contacto", RIGHT - LEFT - 32, 8.5), LEFT + 16, y - 55, 8.5, false, COLORS.muted);
      y -= 94;

      const infoWidth = (RIGHT - LEFT - 20) / 3;
      const infoItems: [string, string][] = [
        ["Folio Odoo", data.result.folio || `#${data.result.id}`],
        ["Vendedor", data.seller?.name || "RapyVet"],
        ["Estado", data.result.status || "Cotización"],
      ];
      infoItems.forEach(([label, value], index) => {
        const x = LEFT + index * (infoWidth + 10);
        rect(x, y - 48, infoWidth, 48, COLORS.surface);
        text(label.toLocaleUpperCase("es-MX"), x + 12, y - 17, 7, true, COLORS.faint);
        text(fitText(value, infoWidth - 24, 11, true), x + 12, y - 34, 11, true, COLORS.ink);
      });
      y -= 72;
    } else {
      text(`${data.customer.name.toLocaleUpperCase("es-MX")} - continuación`, LEFT, y, 9, true, COLORS.muted);
      y -= 20;
    }

    rect(LEFT, y - 24, RIGHT - LEFT, 24, COLORS.band);
    text("Cant.", LEFT + 10, y - 15.5, 8, true, COLORS.ink);
    text("Producto", LEFT + 58, y - 15.5, 8, true, COLORS.ink);
    textRight("Precio", RIGHT - 94, y - 15.5, 8, true, COLORS.ink);
    textRight("Importe", RIGHT - 10, y - 15.5, 8, true, COLORS.ink);
    y -= 26;
  };

  startPage(true);

  data.lines.forEach((line) => {
    if (y - ROW_HEIGHT < BOTTOM + 118) startPage(false);
    const lineBottom = y - ROW_HEIGHT + 2;
    rect(LEFT, lineBottom, RIGHT - LEFT, ROW_HEIGHT - 3, COLORS.surface);
    text(String(line.quantity), LEFT + 10, y - 16, 9, true);
    const label = `${line.name}${line.free ? " - Gratis" : ""}`;
    text(fitText(label, 284, 9.5, true), LEFT + 58, y - 13.5, 9.5, true);
    text(fitText(line.code || "Sin SKU", 284, 7.5), LEFT + 58, y - 23.5, 7.5, false, COLORS.faint);
    textRight(line.free ? "$0.00" : money(line.unitPrice), RIGHT - 94, y - 16, 8.5, false, COLORS.muted);
    textRight(money(line.total), RIGHT - 10, y - 16, 9.5, true, line.free ? COLORS.success : COLORS.ink);
    y -= ROW_HEIGHT;
  });

  if (y - 150 < BOTTOM) startPage(false);
  y -= 12;
  rule(y);
  y -= 18;

  if (data.note?.trim()) {
    text("Notas", LEFT, y, 8, true, COLORS.brandBright);
    y -= 14;
    text(fitText(data.note.trim(), RIGHT - LEFT, 8.5), LEFT, y, 8.5, false, COLORS.muted);
    y -= 24;
  }

  const boxWidth = 230;
  const boxLeft = RIGHT - boxWidth;
  rect(boxLeft, y - 86, boxWidth, 86, COLORS.soft);
  text("Resumen", boxLeft + 16, y - 18, 8, true, COLORS.brandBright);
  text("Subtotal", boxLeft + 16, y - 38, 9, false, COLORS.muted);
  textRight(money(data.result.subtotal), RIGHT - 16, y - 38, 9, false, COLORS.ink);
  text("IVA", boxLeft + 16, y - 55, 9, false, COLORS.muted);
  textRight(money(data.result.tax), RIGHT - 16, y - 55, 9, false, COLORS.ink);
  text("Total", boxLeft + 16, y - 75, 11, true, COLORS.ink);
  textRight(money(data.result.total), RIGHT - 16, y - 75, 16, true, COLORS.brandBright);
  y -= 110;
  text("Cotización informativa. La confirmación, pagos y facturación se realizan únicamente en Odoo.", LEFT, Math.max(y, 44), 8, false, COLORS.faint);
  pages.push(content);

  return assemblePdf(
    pages.map((page, index) => {
      const pageLabel = `Página ${index + 1} de ${pages.length}`;
      return (
        page +
        textOp(fitText(`RapyVet Pedidos - ${data.result.folio}`, 340, 7.5), LEFT, 28, 7.5, false, COLORS.faint) +
        textOp(pageLabel, RIGHT - textWidth(pageLabel, 7.5), 28, 7.5, false, COLORS.faint)
      );
    }),
  );
}

export function createQuotationPdfFile(data: QuotationPdfData) {
  const blob = new Blob([buildQuotationPdfBytes(data)], { type: "application/pdf" });
  return new File([blob], quotationPdfFilename(data), { type: "application/pdf" });
}

export function downloadQuotationPdf(data: QuotationPdfData) {
  const blob = new Blob([buildQuotationPdfBytes(data)], { type: "application/pdf" });
  const url = URL.createObjectURL(blob);
  const anchor = document.createElement("a");
  anchor.href = url;
  anchor.download = quotationPdfFilename(data);
  anchor.rel = "noopener";
  document.body.appendChild(anchor);
  anchor.click();
  anchor.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 30_000);
}

export async function shareQuotationPdf(data: QuotationPdfData) {
  if (!navigator.share || typeof File === "undefined") return false;
  const file = createQuotationPdfFile(data);
  const shareData: ShareData = {
    title: `Cotización ${data.result.folio}`,
    text: buildQuotationWhatsAppMessage(data),
    files: [file],
  };
  const canShareFiles = typeof navigator.canShare === "function" ? navigator.canShare(shareData) : false;
  if (!canShareFiles) return false;
  await navigator.share(shareData);
  return true;
}
