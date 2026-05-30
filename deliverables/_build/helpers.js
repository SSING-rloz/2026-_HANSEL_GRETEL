// Shared docx-js helpers for HANSEL/GRETEL deliverables.
const {
  Document, Packer, Paragraph, TextRun, Table, TableRow, TableCell,
  Header, Footer, AlignmentType, LevelFormat, HeadingLevel, BorderStyle,
  WidthType, ShadingType, PageNumber, PageBreak, TableOfContents,
} = require("docx");
const fs = require("fs");

const CONTENT_WIDTH = 9360; // US Letter, 1" margins

const COLORS = {
  h1: "1F3864",
  h2: "2E5496",
  h3: "2E74B5",
  headerFill: "1F3864",
  rowFill: "D9E2F3",
  altFill: "F2F5FB",
  warnFill: "FBE4D5",
  okFill: "E2EFDA",
  privFill: "FCE4E4",
  rule: "2E74B5",
};

function styles() {
  return {
    default: { document: { run: { font: "Arial", size: 21 } } },
    paragraphStyles: [
      { id: "Heading1", name: "Heading 1", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 32, bold: true, font: "Arial", color: COLORS.h1 },
        paragraph: { spacing: { before: 300, after: 160 }, outlineLevel: 0 } },
      { id: "Heading2", name: "Heading 2", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 26, bold: true, font: "Arial", color: COLORS.h2 },
        paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 1 } },
      { id: "Heading3", name: "Heading 3", basedOn: "Normal", next: "Normal", quickFormat: true,
        run: { size: 23, bold: true, font: "Arial", color: COLORS.h3 },
        paragraph: { spacing: { before: 180, after: 80 }, outlineLevel: 2 } },
    ],
  };
}

function numbering() {
  return {
    config: [
      { reference: "bullets", levels: [
        { level: 0, format: LevelFormat.BULLET, text: "•", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 540, hanging: 280 } } } },
        { level: 1, format: LevelFormat.BULLET, text: "◦", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 1080, hanging: 280 } } } },
      ] },
      { reference: "nums", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 540, hanging: 320 } } } },
      ] },
      { reference: "steps", levels: [
        { level: 0, format: LevelFormat.DECIMAL, text: "%1.", alignment: AlignmentType.LEFT,
          style: { paragraph: { indent: { left: 540, hanging: 320 } } } },
      ] },
    ],
  };
}

function H1(text) { return new Paragraph({ heading: HeadingLevel.HEADING_1, children: [new TextRun(text)] }); }
function H2(text) { return new Paragraph({ heading: HeadingLevel.HEADING_2, children: [new TextRun(text)] }); }
function H3(text) { return new Paragraph({ heading: HeadingLevel.HEADING_3, children: [new TextRun(text)] }); }

// paragraph supporting inline bold via array of {t, b, color, code}
function P(parts, opts = {}) {
  const runs = (Array.isArray(parts) ? parts : [{ t: parts }]).map(seg => {
    if (typeof seg === "string") seg = { t: seg };
    return new TextRun({
      text: seg.t,
      bold: !!seg.b,
      italics: !!seg.i,
      color: seg.color,
      font: seg.code ? "Consolas" : undefined,
    });
  });
  return new Paragraph({ children: runs, spacing: { after: opts.after ?? 100 }, ...opts.extra });
}

function Bullet(parts, level = 0) {
  const runs = (Array.isArray(parts) ? parts : [{ t: parts }]).map(seg => {
    if (typeof seg === "string") seg = { t: seg };
    return new TextRun({ text: seg.t, bold: !!seg.b, color: seg.color, font: seg.code ? "Consolas" : undefined });
  });
  return new Paragraph({ numbering: { reference: "bullets", level }, children: runs, spacing: { after: 40 } });
}

function NumItem(parts, ref = "nums") {
  const runs = (Array.isArray(parts) ? parts : [{ t: parts }]).map(seg => {
    if (typeof seg === "string") seg = { t: seg };
    return new TextRun({ text: seg.t, bold: !!seg.b, color: seg.color, font: seg.code ? "Consolas" : undefined });
  });
  return new Paragraph({ numbering: { reference: ref, level: 0 }, children: runs, spacing: { after: 50 } });
}

function Spacer() { return new Paragraph({ children: [], spacing: { after: 60 } }); }

function Rule() {
  return new Paragraph({
    children: [],
    border: { bottom: { style: BorderStyle.SINGLE, size: 6, color: COLORS.rule, space: 1 } },
    spacing: { after: 120 },
  });
}

function Code(text) {
  return new Paragraph({
    shading: { fill: "F2F2F2", type: ShadingType.CLEAR },
    spacing: { before: 40, after: 40 },
    children: [new TextRun({ text, font: "Consolas", size: 19 })],
  });
}

function CodeBlock(lines) {
  return lines.map((ln, idx) => new Paragraph({
    shading: { fill: "F2F2F2", type: ShadingType.CLEAR },
    spacing: { before: idx === 0 ? 60 : 0, after: idx === lines.length - 1 ? 100 : 0 },
    children: [new TextRun({ text: ln === "" ? " " : ln, font: "Consolas", size: 19 })],
  }));
}

const cellBorder = { style: BorderStyle.SINGLE, size: 1, color: "AAB4C8" };
const cellBorders = { top: cellBorder, bottom: cellBorder, left: cellBorder, right: cellBorder };

function cellRuns(content) {
  const segs = Array.isArray(content) ? content : [{ t: String(content) }];
  return segs.map(seg => {
    if (typeof seg === "string") seg = { t: seg };
    return new TextRun({ text: seg.t, bold: !!seg.b, color: seg.color, font: seg.code ? "Consolas" : undefined, size: seg.size });
  });
}

// rows: array of arrays; first row = header. each cell = string | array of segs.
function makeTable(widths, rows, opts = {}) {
  const total = widths.reduce((a, b) => a + b, 0);
  const headerRow = rows[0];
  const bodyRows = rows.slice(1);
  const trs = [];
  trs.push(new TableRow({
    tableHeader: true,
    children: headerRow.map((c, i) => new TableCell({
      borders: cellBorders,
      width: { size: widths[i], type: WidthType.DXA },
      shading: { fill: COLORS.headerFill, type: ShadingType.CLEAR },
      margins: { top: 60, bottom: 60, left: 100, right: 100 },
      children: [new Paragraph({ children: cellRuns(typeof c === "string" ? [{ t: c, b: true, color: "FFFFFF" }] : c.map(s => ({ ...(typeof s === "string" ? { t: s } : s), b: true, color: "FFFFFF" }))) , spacing: { after: 0 } })],
    })),
  }));
  bodyRows.forEach((row, ri) => {
    const fill = row._fill || (ri % 2 === 0 ? COLORS.altFill : "FFFFFF");
    const cells = row._cells || row;
    trs.push(new TableRow({
      children: cells.map((c, i) => new TableCell({
        borders: cellBorders,
        width: { size: widths[i], type: WidthType.DXA },
        shading: { fill, type: ShadingType.CLEAR },
        margins: { top: 50, bottom: 50, left: 100, right: 100 },
        children: [new Paragraph({ children: cellRuns(c), spacing: { after: 0 } })],
      })),
    }));
  });
  return new Table({ width: { size: total, type: WidthType.DXA }, columnWidths: widths, rows: trs });
}

function Callout(title, lines, kind = "warn") {
  const fill = kind === "warn" ? COLORS.warnFill : kind === "ok" ? COLORS.okFill : COLORS.privFill;
  const children = [new Paragraph({ children: [new TextRun({ text: title, bold: true })], spacing: { after: 40 } })];
  lines.forEach(l => children.push(new Paragraph({ children: cellRuns(l), spacing: { after: 20 } })));
  return new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [CONTENT_WIDTH],
    rows: [new TableRow({ children: [new TableCell({
      borders: cellBorders,
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      shading: { fill, type: ShadingType.CLEAR },
      margins: { top: 100, bottom: 100, left: 140, right: 140 },
      children,
    })] })],
  });
}

function sectionProps(footerText) {
  return {
    properties: {
      page: {
        size: { width: 12240, height: 15840 },
        margin: { top: 1296, right: 1440, bottom: 1296, left: 1440 },
      },
    },
    footers: {
      default: new Footer({ children: [new Paragraph({
        alignment: AlignmentType.CENTER,
        border: { top: { style: BorderStyle.SINGLE, size: 4, color: "C7D0E0", space: 6 } },
        children: [
          new TextRun({ text: footerText + "   |   ", size: 16, color: "7F8DA8" }),
          new TextRun({ text: "p. ", size: 16, color: "7F8DA8" }),
          new TextRun({ children: [PageNumber.CURRENT], size: 16, color: "7F8DA8" }),
        ],
      })] }),
    },
  };
}

function TitlePage({ title, subtitle, banner, bannerKind, meta }) {
  const out = [];
  out.push(new Paragraph({ children: [], spacing: { after: 1200 } }));
  title.forEach(line => out.push(new Paragraph({
    alignment: AlignmentType.CENTER,
    spacing: { after: 80 },
    children: [new TextRun({ text: line, bold: true, size: 44, color: COLORS.h1, font: "Arial" })],
  })));
  if (subtitle) out.push(new Paragraph({
    alignment: AlignmentType.CENTER, spacing: { before: 80, after: 400 },
    children: [new TextRun({ text: subtitle, size: 26, color: COLORS.h2 })],
  }));
  // banner box
  const fill = bannerKind === "priv" ? COLORS.privFill : bannerKind === "ok" ? COLORS.okFill : COLORS.warnFill;
  out.push(new Table({
    width: { size: CONTENT_WIDTH, type: WidthType.DXA },
    columnWidths: [CONTENT_WIDTH],
    rows: [new TableRow({ children: [new TableCell({
      borders: cellBorders,
      width: { size: CONTENT_WIDTH, type: WidthType.DXA },
      shading: { fill, type: ShadingType.CLEAR },
      margins: { top: 160, bottom: 160, left: 160, right: 160 },
      children: banner.map(b => new Paragraph({
        alignment: AlignmentType.CENTER, spacing: { after: 40 },
        children: cellRuns(Array.isArray(b) ? b : [{ t: b, b: true }]),
      })),
    })] })],
  }));
  out.push(new Paragraph({ children: [], spacing: { after: 500 } }));
  if (meta) {
    meta.forEach(m => out.push(new Paragraph({
      alignment: AlignmentType.CENTER, spacing: { after: 30 },
      children: [new TextRun({ text: m, size: 19, color: "595959" })],
    })));
  }
  out.push(new Paragraph({ children: [new PageBreak()] }));
  return out;
}

function build(filename, footerText, children) {
  const doc = new Document({
    styles: styles(),
    numbering: numbering(),
    sections: [{ ...sectionProps(footerText), children }],
  });
  return Packer.toBuffer(doc).then(buf => fs.writeFileSync(filename, buf));
}

module.exports = {
  H1, H2, H3, P, Bullet, NumItem, Spacer, Rule, Code, CodeBlock, makeTable,
  Callout, TitlePage, build, CONTENT_WIDTH, COLORS,
  Paragraph, TextRun, PageBreak, TableOfContents, HeadingLevel,
};
