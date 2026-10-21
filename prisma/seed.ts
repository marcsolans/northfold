/**
 * Idempotent seed: `pnpm db:seed` can run any number of times.
 *
 * - Products are upserted by slug and their seed fields kept in sync.
 * - Images are replaced with the seed set (seeded products only).
 * - Variants are upserted by SKU; stock is only set when a variant is created, so re-seeding
 *   never overwrites real inventory.
 * - Users listed in ADMIN_EMAILS are promoted to ADMIN (they must have signed up first).
 */
import "dotenv/config";

import { createPrismaClient } from "../src/lib/prisma-client";

import { defaultStock, SEED_PRODUCTS, type SeedProduct } from "./seed-data";
import { imagesFor } from "./seed-images";

const databaseUrl = process.env.DATABASE_URL;
if (!databaseUrl) {
  console.error("DATABASE_URL is not set. Copy .env.example to .env first.");
  process.exit(1);
}

const prisma = createPrismaClient(databaseUrl);

function skuFor(product: SeedProduct, size: string, colorCode: string): string {
  const category = product.category === "CHILDREN" ? "K" : product.category === "WOMEN" ? "W" : "M";
  return `NF-${category}-${product.code}-${size}-${colorCode}`;
}

async function seedProduct(product: SeedProduct, index: number): Promise<void> {
  const fields = {
    name: product.name,
    description: product.description,
    price: product.price,
    category: product.category,
    productType: product.productType,
    isFeatured: product.isFeatured ?? false,
    isBestseller: product.isBestseller ?? false,
  };

  const saved = await prisma.product.upsert({
    where: { slug: product.slug },
    create: {
      slug: product.slug,
      ...fields,
      // Interleave creation dates across categories so "newest" is a realistic mix.
      createdAt: new Date(Date.UTC(2026, 0, 1 + ((index * 7) % SEED_PRODUCTS.length) * 3)),
    },
    update: fields,
  });

  const siblingIndex = SEED_PRODUCTS.slice(0, index).filter(
    (other) => other.category === product.category && other.productType === product.productType,
  ).length;
  const images = imagesFor(product, siblingIndex);
  await prisma.$transaction([
    prisma.productImage.deleteMany({ where: { productId: saved.id } }),
    prisma.productImage.createMany({
      data: images.map((image, position) => ({
        productId: saved.id,
        url: image.url,
        alt: image.alt,
        publicId: null,
        position,
      })),
    }),
  ]);

  for (const color of product.colors) {
    for (const size of product.sizes) {
      const sku = skuFor(product, size, color.code);
      const stock = product.stock?.[`${size}/${color.code}`] ?? defaultStock(sku);
      await prisma.productVariant.upsert({
        where: { sku },
        create: {
          productId: saved.id,
          sku,
          size,
          colorName: color.name,
          colorHex: color.hex,
          stock,
        },
        update: { size, colorName: color.name, colorHex: color.hex },
      });
    }
  }
}

async function promoteAdmins(): Promise<void> {
  const emails = (process.env.ADMIN_EMAILS ?? "")
    .split(",")
    .map((email) => email.trim().toLowerCase())
    .filter(Boolean);
  if (emails.length === 0) {
    console.info("ADMIN_EMAILS is empty — no users promoted.");
    return;
  }

  const result = await prisma.user.updateMany({
    where: { email: { in: emails } },
    data: { role: "ADMIN" },
  });
  const existing = await prisma.user.findMany({
    where: { email: { in: emails } },
    select: { email: true },
  });
  const missing = emails.filter((email) => !existing.some((user) => user.email === email));
  console.info(`Promoted ${result.count} user(s) to ADMIN.`);
  if (missing.length > 0) {
    console.info(`Not found (sign up first, then re-run \`pnpm db:seed\`): ${missing.join(", ")}`);
  }
}

async function main(): Promise<void> {
  console.info(`Seeding ${SEED_PRODUCTS.length} products…`);
  for (const [index, product] of SEED_PRODUCTS.entries()) {
    await seedProduct(product, index);
  }
  const [products, variants, outOfStock] = await Promise.all([
    prisma.product.count(),
    prisma.productVariant.count(),
    prisma.productVariant.count({ where: { stock: 0 } }),
  ]);
  console.info(`Catalog: ${products} products, ${variants} variants (${outOfStock} out of stock).`);
  await promoteAdmins();
}

main()
  .then(() => prisma.$disconnect())
  .catch(async (error: unknown) => {
    console.error(error);
    await prisma.$disconnect();
    process.exit(1);
  });
