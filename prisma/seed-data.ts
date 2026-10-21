import type { Category, ProductType, Size } from "../src/generated/prisma/enums";

export interface SeedColor {
  name: string;
  hex: string;
  code: string;
}

export interface SeedProduct {
  slug: string;
  name: string;
  description: string;
  price: string;
  category: Category;
  productType: ProductType;
  isFeatured?: boolean;
  isBestseller?: boolean;
  /** Short code used to build SKUs, e.g. "ESS". */
  code: string;
  sizes: Size[];
  colors: SeedColor[];
  /** Explicit stock overrides by "SIZE/COLORCODE"; everything else gets a deterministic level. */
  stock?: Record<string, number>;
  imageCount: 2 | 3 | 4;
}

const C = {
  white: { name: "Chalk White", hex: "#f4f2ec", code: "WHT" },
  charcoal: { name: "Charcoal", hex: "#2b2b29", code: "CHR" },
  sage: { name: "Sage", hex: "#9aa58f", code: "SGE" },
  sand: { name: "Sand", hex: "#d6c6a5", code: "SND" },
  navy: { name: "Fjord Navy", hex: "#22304a", code: "NVY" },
  oat: { name: "Oat", hex: "#e3d9c6", code: "OAT" },
  olive: { name: "Olive", hex: "#5c6243", code: "OLV" },
  stone: { name: "Stone", hex: "#a9a39a", code: "STN" },
  black: { name: "Black", hex: "#141414", code: "BLK" },
  indigo: { name: "Rinse Indigo", hex: "#2e3a55", code: "IND" },
  midWash: { name: "Mid Wash", hex: "#6c82a3", code: "MID" },
  camel: { name: "Camel", hex: "#b08a5b", code: "CML" },
  forest: { name: "Pine", hex: "#2f4b3f", code: "PNE" },
  rust: { name: "Rust", hex: "#a2512e", code: "RST" },
  skyBlue: { name: "Sky Blue", hex: "#b9cfe0", code: "SKY" },
  clay: { name: "Clay", hex: "#c08b74", code: "CLY" },
  ecru: { name: "Ecru", hex: "#ece4d3", code: "ECR" },
  grey: { name: "Heather Grey", hex: "#b9b8b3", code: "GRY" },
  brown: { name: "Chocolate", hex: "#4a3427", code: "CHC" },
} satisfies Record<string, SeedColor>;

const ADULT: Size[] = ["S", "M", "L", "XL"];
const ADULT_WIDE: Size[] = ["XS", "S", "M", "L", "XL", "XXL"];
const WOMEN: Size[] = ["XS", "S", "M", "L"];
const KIDS: Size[] = ["XS", "S", "M", "L"];
const SHOES: Size[] = ["S", "M", "L", "XL"];

export const SEED_PRODUCTS: SeedProduct[] = [
  // ── Men ──────────────────────────────────────────────────────────────────
  {
    slug: "essential-organic-cotton-tee",
    name: "Essential Organic Cotton Tee",
    description:
      "Our everyday crew-neck in 180 gsm organic cotton jersey. Garment-washed for a soft hand, with a clean neckline that keeps its shape wash after wash. Regular fit; take your usual size.",
    price: "32.00",
    category: "MEN",
    productType: "TSHIRT",
    isBestseller: true,
    code: "ESS",
    sizes: ADULT_WIDE,
    colors: [C.white, C.charcoal, C.sage],
    stock: { "XXL/SGE": 0, "XS/CHR": 3 },
    imageCount: 3,
  },
  {
    slug: "heavyweight-pocket-tee",
    name: "Heavyweight Pocket Tee",
    description:
      "A structured 240 gsm tee with a dropped shoulder and a single chest pocket. Dense, slightly boxy and built to last — the kind of T-shirt that gets better with every wear.",
    price: "38.00",
    category: "MEN",
    productType: "TSHIRT",
    code: "HVY",
    sizes: ADULT,
    colors: [C.oat, C.navy],
    imageCount: 2,
  },
  {
    slug: "oxford-button-down-shirt",
    name: "Oxford Button-Down Shirt",
    description:
      "Woven from a soft, slubby Oxford cloth with a classic button-down collar and a curved hem that works tucked or untucked. Mother-of-pearl buttons and single-needle stitching throughout.",
    price: "79.00",
    category: "MEN",
    productType: "SHIRT",
    isFeatured: true,
    code: "OXF",
    sizes: ADULT_WIDE,
    colors: [C.white, C.skyBlue],
    stock: { "M/SKY": 2, "L/SKY": 0 },
    imageCount: 3,
  },
  {
    slug: "linen-camp-collar-shirt",
    name: "Linen Camp-Collar Shirt",
    description:
      "European flax linen in a relaxed, boxy cut with an open camp collar. Breathable and lightweight, it softens beautifully over time. Made for warm days and long evenings.",
    price: "85.00",
    category: "MEN",
    productType: "SHIRT",
    code: "LIN",
    sizes: ADULT,
    colors: [C.sand, C.olive],
    imageCount: 2,
  },
  {
    slug: "brushed-fleece-hoodie",
    name: "Brushed Fleece Hoodie",
    description:
      "A midweight hoodie in brushed-back organic cotton fleece. Double-layered hood, ribbed cuffs and a kangaroo pocket. Cosy without bulk, with a relaxed fit through the body.",
    price: "95.00",
    category: "MEN",
    productType: "HOODIE",
    isBestseller: true,
    isFeatured: true,
    code: "FLC",
    sizes: ADULT_WIDE,
    colors: [C.grey, C.charcoal, C.forest],
    stock: { "M/PNE": 4, "L/PNE": 1, "XL/PNE": 0 },
    imageCount: 4,
  },
  {
    slug: "waxed-cotton-field-jacket",
    name: "Waxed Cotton Field Jacket",
    description:
      "A four-pocket field jacket in British waxed cotton that shrugs off wind and drizzle. Corduroy-lined collar, brass snaps and a quilted lining for the colder months.",
    price: "245.00",
    category: "MEN",
    productType: "JACKET",
    isFeatured: true,
    code: "FLD",
    sizes: ADULT,
    colors: [C.olive, C.navy],
    stock: { "S/OLV": 2, "XL/NVY": 0 },
    imageCount: 3,
  },
  {
    slug: "quilted-liner-jacket",
    name: "Quilted Liner Jacket",
    description:
      "Lightweight onion-quilted jacket with recycled insulation. Wear it on its own in spring or layer it under a coat when the temperature drops. Packs down into its own pocket.",
    price: "165.00",
    category: "MEN",
    productType: "JACKET",
    code: "QLT",
    sizes: ADULT,
    colors: [C.black, C.stone],
    imageCount: 2,
  },
  {
    slug: "slim-selvedge-jeans",
    name: "Slim Selvedge Jeans",
    description:
      "14 oz Japanese selvedge denim cut slim through the thigh with a gentle taper. Raw and unwashed, they mould to you over time. Button fly, chain-stitched hems.",
    price: "129.00",
    category: "MEN",
    productType: "JEANS",
    isBestseller: true,
    code: "SLV",
    sizes: ADULT,
    colors: [C.indigo, C.black],
    stock: { "M/IND": 3 },
    imageCount: 3,
  },
  {
    slug: "relaxed-wool-blend-trousers",
    name: "Relaxed Wool-Blend Trousers",
    description:
      "Soft-tailored trousers in a recycled wool blend with a single pleat and a relaxed, straight leg. An easy alternative to chinos that dresses up or down.",
    price: "139.00",
    category: "MEN",
    productType: "TROUSERS",
    code: "WOL",
    sizes: ADULT,
    colors: [C.charcoal, C.camel],
    imageCount: 2,
  },
  {
    slug: "utility-chino-shorts",
    name: "Utility Chino Shorts",
    description:
      "Seven-inch shorts in a garment-dyed cotton twill with a hint of stretch. Deep pockets, a clean flat front and a fit that sits just above the knee.",
    price: "59.00",
    category: "MEN",
    productType: "SHORTS",
    code: "CHS",
    sizes: ADULT,
    colors: [C.sand, C.navy],
    stock: { "S/NVY": 0, "XL/SND": 0 },
    imageCount: 2,
  },
  {
    slug: "minimal-leather-sneakers",
    name: "Minimal Leather Sneakers",
    description:
      "Low-profile sneakers in full-grain Italian leather on a stitched natural rubber sole. No logos, no fuss — just a clean silhouette that goes with everything. Sizes: S (EU 40–41), M (42–43), L (44–45), XL (46).",
    price: "165.00",
    category: "MEN",
    productType: "SHOES",
    isFeatured: true,
    isBestseller: true,
    code: "SNK",
    sizes: SHOES,
    colors: [C.white, C.black],
    stock: { "M/WHT": 5, "L/WHT": 2 },
    imageCount: 3,
  },
  // ── Women ────────────────────────────────────────────────────────────────
  {
    slug: "boxy-cotton-tee",
    name: "Boxy Cotton Tee",
    description:
      "A cropped, boxy tee in dense organic cotton with a slightly raised neckline. Pairs perfectly with high-rise denim and wide-leg trousers.",
    price: "34.00",
    category: "WOMEN",
    productType: "TSHIRT",
    isBestseller: true,
    code: "BXY",
    sizes: WOMEN,
    colors: [C.white, C.black, C.clay],
    stock: { "XS/CLY": 0 },
    imageCount: 3,
  },
  {
    slug: "relaxed-poplin-shirt",
    name: "Relaxed Poplin Shirt",
    description:
      "Crisp cotton poplin in an oversized fit with a dropped shoulder and a long, curved hem. Wear it buttoned, open over a tee or tied at the waist.",
    price: "89.00",
    category: "WOMEN",
    productType: "SHIRT",
    isFeatured: true,
    code: "POP",
    sizes: WOMEN,
    colors: [C.white, C.skyBlue],
    imageCount: 3,
  },
  {
    slug: "silk-blend-blouse",
    name: "Silk-Blend Blouse",
    description:
      "A fluid blouse in a washable silk and organic cotton blend, with a softly gathered yoke and covered buttons. Quietly elegant from desk to dinner.",
    price: "110.00",
    category: "WOMEN",
    productType: "SHIRT",
    code: "SLK",
    sizes: WOMEN,
    colors: [C.ecru, C.charcoal],
    stock: { "S/ECR": 3, "M/ECR": 1 },
    imageCount: 2,
  },
  {
    slug: "oversized-loopback-hoodie",
    name: "Oversized Loopback Hoodie",
    description:
      "Heavyweight loopback cotton with an oversized, slouchy fit, dropped shoulders and a roomy hood. The weekend essential you will reach for every time.",
    price: "98.00",
    category: "WOMEN",
    productType: "HOODIE",
    isBestseller: true,
    code: "LPB",
    sizes: WOMEN,
    colors: [C.oat, C.sage],
    imageCount: 3,
  },
  {
    slug: "double-faced-wool-coat",
    name: "Double-Faced Wool Coat",
    description:
      "An unlined, hand-finished coat in double-faced Italian wool. Dropped shoulders, a relaxed silhouette and a self-tie belt. Warm, light and endlessly wearable.",
    price: "320.00",
    category: "WOMEN",
    productType: "JACKET",
    isFeatured: true,
    code: "DFC",
    sizes: WOMEN,
    colors: [C.camel, C.charcoal],
    stock: { "XS/CML": 2, "L/CHR": 0 },
    imageCount: 4,
  },
  {
    slug: "cropped-denim-jacket",
    name: "Cropped Denim Jacket",
    description:
      "A cropped trucker jacket in rigid organic denim with a boxy fit and tonal buttons. A modern take on a timeless layer.",
    price: "119.00",
    category: "WOMEN",
    productType: "JACKET",
    code: "CDJ",
    sizes: WOMEN,
    colors: [C.midWash, C.ecru],
    imageCount: 2,
  },
  {
    slug: "high-rise-straight-jeans",
    name: "High-Rise Straight Jeans",
    description:
      "Our best-selling jean: a high rise, a straight leg and an ankle-grazing length in comfort-stretch organic denim. Flattering, easy and made to last.",
    price: "125.00",
    category: "WOMEN",
    productType: "JEANS",
    isBestseller: true,
    isFeatured: true,
    code: "HRS",
    sizes: WOMEN,
    colors: [C.midWash, C.indigo],
    stock: { "S/MID": 4, "M/MID": 2 },
    imageCount: 3,
  },
  {
    slug: "pleated-wide-leg-trousers",
    name: "Pleated Wide-Leg Trousers",
    description:
      "Fluid crepe trousers with double front pleats, a high waist and a generous wide leg that moves beautifully. Side pockets and a hidden hook closure.",
    price: "135.00",
    category: "WOMEN",
    productType: "TROUSERS",
    code: "PWL",
    sizes: WOMEN,
    colors: [C.black, C.stone],
    imageCount: 2,
  },
  {
    slug: "linen-drawstring-shorts",
    name: "Linen Drawstring Shorts",
    description:
      "Relaxed, high-waisted shorts in washed European linen with an elasticated back and a cotton drawstring. Light, breezy and made for summer.",
    price: "65.00",
    category: "WOMEN",
    productType: "SHORTS",
    code: "LDS",
    sizes: WOMEN,
    colors: [C.oat, C.olive],
    stock: { "XS/OLV": 0, "L/OAT": 0 },
    imageCount: 2,
  },
  {
    slug: "suede-ankle-boots",
    name: "Suede Ankle Boots",
    description:
      "Water-repellent suede boots with a sleek almond toe, a comfortable 45 mm block heel and a leather-lined footbed. Sizes: S (EU 36–37), M (38–39), L (40–41), XL (42).",
    price: "210.00",
    category: "WOMEN",
    productType: "SHOES",
    isFeatured: true,
    code: "SAB",
    sizes: SHOES,
    colors: [C.brown, C.black],
    stock: { "S/CHC": 1, "XL/BLK": 0 },
    imageCount: 3,
  },
  // ── Children ─────────────────────────────────────────────────────────────
  {
    slug: "kids-striped-cotton-tee",
    name: "Kids' Striped Cotton Tee",
    description:
      "A soft Breton-stripe tee in organic cotton, built for play and endless washing. Sizes: XS (2–3 y), S (4–5 y), M (6–7 y), L (8–9 y).",
    price: "22.00",
    category: "CHILDREN",
    productType: "TSHIRT",
    isBestseller: true,
    code: "KST",
    sizes: KIDS,
    colors: [C.navy, C.rust],
    imageCount: 2,
  },
  {
    slug: "kids-zip-fleece-hoodie",
    name: "Kids' Zip Fleece Hoodie",
    description:
      "A cosy full-zip hoodie in brushed recycled fleece with a chin guard and reinforced elbows. Sizes: XS (2–3 y), S (4–5 y), M (6–7 y), L (8–9 y).",
    price: "45.00",
    category: "CHILDREN",
    productType: "HOODIE",
    code: "KZH",
    sizes: KIDS,
    colors: [C.forest, C.grey],
    stock: { "M/PNE": 2 },
    imageCount: 2,
  },
  {
    slug: "kids-padded-puffer-jacket",
    name: "Kids' Padded Puffer Jacket",
    description:
      "Warm, water-repellent puffer with recycled padding, a fixed hood and reflective details for darker days. Sizes: XS (2–3 y), S (4–5 y), M (6–7 y), L (8–9 y).",
    price: "89.00",
    category: "CHILDREN",
    productType: "JACKET",
    isFeatured: true,
    code: "KPJ",
    sizes: KIDS,
    colors: [C.navy, C.clay],
    stock: { "L/CLY": 0 },
    imageCount: 2,
  },
  {
    slug: "kids-stretch-denim-jeans",
    name: "Kids' Stretch Denim Jeans",
    description:
      "Comfortable stretch denim with an adjustable waist and reinforced knees for climbing, crawling and everything in between. Sizes: XS (2–3 y) to L (8–9 y).",
    price: "42.00",
    category: "CHILDREN",
    productType: "JEANS",
    code: "KDJ",
    sizes: KIDS,
    colors: [C.midWash],
    imageCount: 2,
  },
  {
    slug: "kids-canvas-sneakers",
    name: "Kids' Canvas Sneakers",
    description:
      "Easy on, easy off: organic canvas sneakers with a hook-and-loop strap and a flexible natural rubber sole. Sizes: XS (EU 26–27), S (28–29), M (30–31), L (32–33).",
    price: "48.00",
    category: "CHILDREN",
    productType: "SHOES",
    isBestseller: true,
    code: "KCS",
    sizes: KIDS,
    colors: [C.white, C.navy],
    stock: { "XS/NVY": 3 },
    imageCount: 2,
  },
];

/** Deterministic stock level for a SKU (idempotent seeds, varied inventory). */
export function defaultStock(sku: string): number {
  let hash = 0;
  for (const char of sku) hash = (hash * 31 + char.charCodeAt(0)) >>> 0;
  const levels = [8, 12, 15, 20, 24, 30, 6, 18];
  return levels[hash % levels.length] ?? 10;
}
