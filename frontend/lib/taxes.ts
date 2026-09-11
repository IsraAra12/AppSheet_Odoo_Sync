import type { CartLine, Product, Tax } from "@/lib/types";

export type Amounts = { untaxed: number; tax: number; total: number };

/** `unknown`: el producto tiene impuestos en Odoo, pero el catálogo no trajo su definición. */
export type TaxStatus = "taxed" | "untaxed" | "unknown";

type PricedLine = Pick<CartLine, "productId" | "quantity" | "unitPrice" | "free">;

export type Pricing = {
  /** Precio unitario con impuestos. `unitPrice` es el price_unit de Odoo (sin IVA). */
  unit: (productId: number, unitPrice: number) => number;
  line: (line: PricedLine) => Amounts;
  order: (lines: PricedLine[]) => Amounts;
  taxStatus: (productId: number) => TaxStatus;
};

const ZERO: Amounts = { untaxed: 0, tax: 0, total: 0 };

function round2(value: number) {
  return Math.round((value + Number.EPSILON) * 100) / 100;
}

function expandTaxes(taxIds: number[], taxesById: Map<number, Tax>) {
  const result: Tax[] = [];
  const seen = new Set<number>();
  const add = (taxId: number) => {
    if (seen.has(taxId)) return;
    seen.add(taxId);
    const tax = taxesById.get(taxId);
    if (!tax) return;
    if (tax.amount_type === "group") tax.children_tax_ids.forEach(add);
    else result.push(tax);
  };
  taxIds.forEach(add);
  return result.sort((a, b) => a.sequence - b.sequence || a.id - b.id);
}

function taxAmount(tax: Tax, base: number, quantity: number) {
  if (tax.amount_type === "fixed") return tax.amount * quantity;
  if (tax.amount_type === "division") {
    const rate = tax.amount / 100;
    return rate >= 0 && rate < 1 ? base / (1 - rate) - base : 0;
  }
  return base * (tax.amount / 100);
}

function amountsFromBase(base: number, taxes: Tax[], quantity: number) {
  let currentBase = base;
  return taxes.map((tax) => {
    const amount = taxAmount(tax, tax.is_base_affected ? currentBase : base, quantity);
    if (tax.include_base_amount) currentBase += amount;
    return { tax, amount };
  });
}

/** Mismo cálculo que rapyvet/taxes.py, por línea como lo hace Odoo (`compute_all`). */
function computeLine(unitPrice: number, quantity: number, taxes: Tax[]): Amounts {
  const price = Math.max(0, unitPrice) * quantity;
  if (!taxes.length || price === 0) return { untaxed: round2(price), tax: 0, total: round2(price) };

  let base = price;
  if (taxes.some((tax) => tax.price_include)) {
    // Los impuestos válidos de Odoo producen una función monótona; 80
    // iteraciones dejan un margen muy inferior a un centavo.
    const includedTotal = (candidate: number) =>
      candidate + amountsFromBase(candidate, taxes, quantity).reduce((sum, item) => sum + (item.tax.price_include ? item.amount : 0), 0);
    let low = 0;
    let high = Math.max(price, 1);
    for (let step = 0; step < 80; step += 1) {
      const middle = (low + high) / 2;
      if (includedTotal(middle) < price) low = middle;
      else high = middle;
    }
    base = (low + high) / 2;
  }

  const untaxed = round2(base);
  const tax = round2(amountsFromBase(base, taxes, quantity).reduce((sum, item) => sum + item.amount, 0));
  return { untaxed, tax, total: round2(untaxed + tax) };
}

export function createPricing(products: Product[], taxes: Tax[] = []): Pricing {
  const taxesById = new Map(taxes.map((tax) => [tax.id, tax]));
  const productTaxes = new Map(products.map((product) => [product.id, expandTaxes(product.tax_ids, taxesById)]));
  const productTaxIds = new Map(products.map((product) => [product.id, product.tax_ids]));
  const taxesFor = (productId: number) => productTaxes.get(productId) ?? [];

  const line = (item: PricedLine) => (item.free ? ZERO : computeLine(item.unitPrice, item.quantity, taxesFor(item.productId)));

  return {
    unit: (productId, unitPrice) => computeLine(unitPrice, 1, taxesFor(productId)).total,
    line,
    order: (lines) =>
      lines.reduce<Amounts>((sum, item) => {
        const amounts = line(item);
        return { untaxed: round2(sum.untaxed + amounts.untaxed), tax: round2(sum.tax + amounts.tax), total: round2(sum.total + amounts.total) };
      }, ZERO),
    taxStatus: (productId) =>
      taxesFor(productId).length ? "taxed" : productTaxIds.get(productId)?.length ? "unknown" : "untaxed",
  };
}
