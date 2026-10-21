import type { Category } from "@/generated/prisma/enums";

/** Editorial imagery from Unsplash (Unsplash License). */
function unsplash(id: string, width: number): string {
  return `https://images.unsplash.com/${id}?auto=format&fit=crop&w=${width}&q=80`;
}

export const HERO_IMAGE = {
  src: unsplash("photo-1490481651871-ab68de25d43d", 2000),
  alt: "Minimal clothing rail of neutral-toned tops and blouses against a white wall",
};

export const SECONDARY_HERO_IMAGE = {
  src: unsplash("photo-1558769132-cb1aea458c5e", 1600),
  alt: "Rail of cream, beige and brown knitwear beside dried pampas grass",
};

export const CATEGORY_IMAGES: Record<Category, { src: string; alt: string }> = {
  MEN: {
    src: unsplash("photo-1479064555552-3ef4979f8908", 1200),
    alt: "Flat lay of leather boots, grey chinos and a white t-shirt",
  },
  WOMEN: {
    src: unsplash("photo-1619086303291-0ef7699e4b31", 1200),
    alt: "Woman in a camel coat and white jeans walking down a city street",
  },
  CHILDREN: {
    src: unsplash("photo-1604467794349-0b74285de7e7", 1200),
    alt: "Rail of children's printed clothes on wooden hangers",
  },
};
