/**
 * Seed product photography from Unsplash (free to use under the Unsplash License).
 * Every photo was checked to load and to match its bucket; `alt` describes what is visible.
 */
import type { Category, ProductType } from "../src/generated/prisma/enums";

import type { SeedProduct } from "./seed-data";

interface SeedPhoto {
  id: string;
  alt: string;
}

const PHOTOS: Record<Category, Partial<Record<ProductType, SeedPhoto[]>>> = {
  MEN: {
    TSHIRT: [
      {
        id: "photo-1581655353564-df123a1eb820",
        alt: "White t-shirt on a hanger against a dark concrete wall",
      },
      {
        id: "photo-1586790170083-2f9ceadc732d",
        alt: "Bearded man in a plain white crew-neck t-shirt against a beige wall",
      },
      {
        id: "photo-1574180566232-aaad1b5b8450",
        alt: "Man in a fitted white t-shirt and black trousers, hands in pockets",
      },
      {
        id: "photo-1618517351616-38fb9c5210c6",
        alt: "Man in sunglasses wearing a plain black t-shirt outdoors",
      },
      {
        id: "photo-1633966887768-64f9a867bdba",
        alt: "Teal pocket t-shirt laid flat on a grey concrete surface",
      },
      {
        id: "photo-1519058082700-08a0b56da9b4",
        alt: "Bearded man in an olive green t-shirt in a misty forest",
      },
      {
        id: "photo-1480455624313-e29b44bbfde1",
        alt: "Man in a burgundy v-neck t-shirt outdoors at golden hour",
      },
      {
        id: "photo-1564584217132-2271feaeb3c5",
        alt: "Light blue heather t-shirt on a hanger against a white wall",
      },
      {
        id: "photo-1620799139834-6b8f844fbe61",
        alt: "Two folded white t-shirts in a flat lay with white sneakers",
      },
      {
        id: "photo-1666358054407-9ea933dadf41",
        alt: "Plain white t-shirt product shot on a white background",
      },
      {
        id: "photo-1666358059751-3accf39c2d95",
        alt: "Beige crew-neck t-shirt product shot on a white background",
      },
      {
        id: "photo-1523381294911-8d3cead13475",
        alt: "Row of sage green t-shirts on wooden hangers",
      },
      {
        id: "photo-1521572163474-6864f9cf17ab",
        alt: "Close-up of a man wearing a plain white crew-neck t-shirt",
      },
    ],
    SHIRT: [
      {
        id: "photo-1589310243389-96a5483213a8",
        alt: "Young man in a light teal button-down shirt and chinos among autumn leaves",
      },
      {
        id: "photo-1563630423918-b58f07336ac9",
        alt: "Smiling man in glasses wearing a navy micro-dot button-up shirt",
      },
      {
        id: "photo-1588359348347-9bc6cbbb689e",
        alt: "Smiling man in a lavender button-down shirt and jeans",
      },
      {
        id: "photo-1604695573706-53170668f6a6",
        alt: "Man in a pale blue oxford shirt and dark trousers",
      },
      {
        id: "photo-1611312449412-6cefac5dc3e4",
        alt: "Black and grey buffalo-check flannel shirt on a hanger against black",
      },
      {
        id: "photo-1603252110481-7ba873bf42ab",
        alt: "White, light blue and pink dress shirts on wooden hangers",
      },
      {
        id: "photo-1602810319428-019690571b5b",
        alt: "Folded dress shirts in burgundy, white and blue patterns",
      },
      {
        id: "photo-1603252109612-24fa03d145c8",
        alt: "Close-up of a man in a crisp white dress shirt against a tan background",
      },
      {
        id: "photo-1598032895397-b9472444bf93",
        alt: "Two folded dress shirts with ties on a grey background",
      },
      {
        id: "photo-1558171813-4c088753af8f",
        alt: "Light blue chambray shirt draped over a red folding chair",
      },
    ],
    HOODIE: [
      {
        id: "photo-1578768079052-aa76e52ff62e",
        alt: "Man in a brown hooded sweatshirt with the hood up against dark steps",
      },
      {
        id: "photo-1556821840-3a63f95609a7",
        alt: "Man in a grey hoodie seen from behind, looking over a landscape",
      },
      {
        id: "photo-1620799140408-edc6dcb6d633",
        alt: "White crew-neck sweatshirt flat lay with white sneakers and grey jeans",
      },
      {
        id: "photo-1620799140188-3b2a02fd9a77",
        alt: "White hoodie on a hanger beside light jeans and dried palm leaves",
      },
      {
        id: "photo-1685328403783-00925c2a4301",
        alt: "Man in a pale sage hooded sweatshirt in soft light",
      },
      {
        id: "photo-1632073143817-8cd5b2165e20",
        alt: "Man in a grey hooded sweatshirt against a beige wall",
      },
      {
        id: "photo-1506634572416-48cdfe530110",
        alt: "Man in sunglasses wearing a burgundy knit sweater",
      },
      {
        id: "photo-1610901157620-340856d0a50f",
        alt: "Man in a dark green cable-knit sweater on a rooftop",
      },
    ],
    JACKET: [
      {
        id: "photo-1591047139829-d91aecb6caea",
        alt: "Rust-coloured bomber jacket held up on a hanger",
      },
      {
        id: "photo-1611312449408-fcece27cdbb7",
        alt: "Dark denim jacket with a corduroy collar on a hanger against black",
      },
      {
        id: "photo-1619603364904-c0498317e145",
        alt: "Man in a camel overcoat and brown turtleneck against a beige wall",
      },
      {
        id: "photo-1559582798-678dfc71ccd8",
        alt: "Man in a camel coat walking past a stone doorway with a holdall",
      },
      {
        id: "photo-1544923246-77307dd654cb",
        alt: "Man in glasses wearing a sherpa-lined denim jacket",
      },
      {
        id: "photo-1548883354-94bcfe321cbb",
        alt: "Man in an olive hooded field parka in a forest",
      },
      {
        id: "photo-1617114919297-3c8ddb01f599",
        alt: "Man in a tan suede jacket and blue jeans by a stone bench",
      },
      {
        id: "photo-1592878849122-facb97520f9e",
        alt: "Man in a black double-breasted blazer over a burgundy turtleneck",
      },
      { id: "photo-1633655442168-c6ef0ed2f984", alt: "Tan wool blazer on a tailor's mannequin" },
      {
        id: "photo-1614252369475-531eba835eb1",
        alt: "Man in sunglasses wearing a tan leather jacket",
      },
    ],
    JEANS: [
      {
        id: "photo-1624378439575-d8705ad7ae80",
        alt: "Dark wash straight-leg jeans laid flat on white fabric",
      },
      {
        id: "photo-1555689502-c4b22d76c56f",
        alt: "Man in slim blue jeans and black sneakers against a brick wall",
      },
      { id: "photo-1576995853123-5a10305d93c0", alt: "Assorted jeans hanging on wooden hangers" },
      {
        id: "photo-1602293589930-45aad59ba3ab",
        alt: "Light wash jeans on a wooden hanger in soft light",
      },
      {
        id: "photo-1604176354204-9268737828e4",
        alt: "Stack of folded jeans in light to dark washes",
      },
      { id: "photo-1715758890151-2c15d5d482aa", alt: "Rail of blue jeans on hangers in a shop" },
      {
        id: "photo-1714143136367-7bb68f3f0669",
        alt: "Folded mid-wash jeans on a light grey background",
      },
      {
        id: "photo-1714143136372-ddaf8b606da7",
        alt: "Mid-wash slim jeans with rolled hems on a light grey background",
      },
    ],
    TROUSERS: [
      {
        id: "photo-1584865288642-42078afe6942",
        alt: "Man in black tapered trousers, white shirt and white sneakers",
      },
      {
        id: "photo-1473966968600-fa801b869a1a",
        alt: "Man in khaki chinos and white sneakers with a denim jacket",
      },
      {
        id: "photo-1513373319109-eb154073eb0b",
        alt: "Flat lay of rust chinos, brown leather boots and a belt on white",
      },
      {
        id: "photo-1544441893-675973e31985",
        alt: "Flat lay of grey chinos, black t-shirt and white sneakers on a dark background",
      },
      {
        id: "photo-1488161628813-04466f872be2",
        alt: "Man in rust trousers and a black jacket sitting below a round window",
      },
      {
        id: "photo-1552374196-1ab2a1c593e8",
        alt: "Man in light trousers and a camel blazer seated on a wooden stool",
      },
    ],
    SHORTS: [
      {
        id: "photo-1621496503717-095a410e1566",
        alt: "Man in a white t-shirt and sage shorts walking on a beach",
      },
      {
        id: "photo-1697319452360-ee47502e39f6",
        alt: "Man in white chino shorts and a striped shirt walking down a street",
      },
      {
        id: "photo-1563389234808-52344934935c",
        alt: "Man in a navy short-sleeve shirt and khaki shorts in the city",
      },
    ],
    SHOES: [
      {
        id: "photo-1608256246200-53e635b5b65f",
        alt: "Pair of dark brown leather lace-up boots on a dark background",
      },
      {
        id: "photo-1638609348722-aa2a3a67db26",
        alt: "Tan leather brogue boots on an olive background",
      },
      {
        id: "photo-1449505278894-297fdb3edbc1",
        alt: "Pair of brown leather derby shoes on a wooden floor",
      },
      {
        id: "photo-1616406432452-07bc5938759d",
        alt: "Brown leather horsebit loafers on navy velvet",
      },
      { id: "photo-1520639888713-7851133b1ed0", alt: "Man lacing brown leather work boots" },
      {
        id: "photo-1533867617858-e7b97e060509",
        alt: "Brown double monk-strap shoe on a wooden surface",
      },
      {
        id: "photo-1626947346165-4c2288dadc2a",
        alt: "Dark grey canvas desert boot on a white background",
      },
      {
        id: "photo-1603808033192-082d6919d3e1",
        alt: "White and tan minimal sneakers stacked on an orange background",
      },
      {
        id: "photo-1614252235316-8c857d38b5f4",
        alt: "Close-up of brown leather derby shoes on white fabric",
      },
      {
        id: "photo-1534233650908-b471f2350922",
        alt: "Worn tan leather lace-up boots on a wooden floor",
      },
    ],
  },
  WOMEN: {
    TSHIRT: [
      {
        id: "photo-1525171254930-643fc658b64e",
        alt: "Stack of tank tops in black, grey and white",
      },
      {
        id: "photo-1624206112918-f140f087f9b5",
        alt: "Smiling woman in a white sleeveless top and jeans",
      },
      {
        id: "photo-1583744946564-b52ac1c389c8",
        alt: "Woman in a black t-shirt and blue jeans against a light grey wall",
      },
      {
        id: "photo-1482826496886-09fe37f30633",
        alt: "Woman in a navy and yellow striped long-sleeve top holding a camera",
      },
    ],
    SHIRT: [
      {
        id: "photo-1564257631407-4deb1f99d992",
        alt: "White floral-embroidered short-sleeve blouse tied at the waist",
      },
      {
        id: "photo-1608234807905-4466023792f5",
        alt: "Woman in a white blouse with a black neck tie and black skirt",
      },
      {
        id: "photo-1519763246425-1d41fcb282d6",
        alt: "Woman in a white ruffled blouse with a black bow and jeans",
      },
      {
        id: "photo-1583496661160-fb5886a0aaaa",
        alt: "Woman in a striped button-up shirt tucked into a black skirt",
      },
      {
        id: "photo-1611042553365-9b101441c135",
        alt: "Woman in a cream blouse and wide-brim hat on a dark background",
      },
      {
        id: "photo-1581338834647-b0fb40704e21",
        alt: "Woman in a white shirt with suspenders and a teal skirt",
      },
      {
        id: "photo-1596755094514-f87e34085b2c",
        alt: "Blue printed button-up shirt on a hanger against a grey wall",
      },
    ],
    HOODIE: [
      {
        id: "photo-1578587018452-892bacefd3f2",
        alt: "Woman in an orange sweatshirt and blue jeans",
      },
      { id: "photo-1631541909061-71e349d1f203", alt: "Oatmeal chunky knit sweater on a hanger" },
      { id: "photo-1624623278313-a930126a11c3", alt: "Stack of folded cream knit sweaters" },
      {
        id: "photo-1574201635302-388dd92a4c3f",
        alt: "Woman pulling on a white ribbed knit sweater",
      },
      {
        id: "photo-1589697547048-962940abc062",
        alt: "Woman in a soft pink knit sweater in an autumn park",
      },
      {
        id: "photo-1643015862949-5c8d15a4242e",
        alt: "Close-up of cream, sage and blush cable-knit sweaters",
      },
      {
        id: "photo-1509319117193-57bab727e09d",
        alt: "Knit cardigans and sweaters on white hangers",
      },
    ],
    JACKET: [
      {
        id: "photo-1539533018447-63fcce2678e3",
        alt: "Woman in a belted camel trench coat on stone steps",
      },
      { id: "photo-1544022613-e87ca75a784a", alt: "Woman in an olive utility jacket and beanie" },
      {
        id: "photo-1608063615781-e2ef8c73d114",
        alt: "Woman in a brown shearling-collar jacket and plaid shirt",
      },
      {
        id: "photo-1525450824786-227cbef70703",
        alt: "Woman in sunglasses wearing a black and white gingham coat",
      },
      {
        id: "photo-1485462537746-965f33f7f6a7",
        alt: "Woman in a pink wool coat in a stone arcade",
      },
      {
        id: "photo-1618244972963-dbee1a7edc95",
        alt: "Woman in a camel coat over a sage knit dress",
      },
      {
        id: "photo-1632149877166-f75d49000351",
        alt: "Woman in an oversized white coat and black boots on a peach background",
      },
      { id: "photo-1571513722275-4b41940f54b8", alt: "Woman in a cream tailored blazer suit" },
      {
        id: "photo-1551028719-00167b16eac5",
        alt: "Black leather biker jacket on a hanger on white sheets",
      },
      {
        id: "photo-1608234808654-2a8875faa7fd",
        alt: "Woman in a grey check double-breasted blazer",
      },
      { id: "photo-1635097247472-dfc3e652db97", alt: "Close-up of a woman in a camel wool coat" },
    ],
    JEANS: [
      {
        id: "photo-1584370848010-d7fe6bc767ec",
        alt: "Woman in light wash skinny jeans and gold flats on white",
      },
      {
        id: "photo-1475178626620-a4d074967452",
        alt: "Woman in light blue skinny jeans and a white shirt",
      },
      {
        id: "photo-1598554747436-c9293d6a588f",
        alt: "Woman in straight-leg jeans and a white sleeveless top, one foot on a stool",
      },
      {
        id: "photo-1603217192634-61068e4d4bf9",
        alt: "Legs in light skinny jeans and white sneakers resting on a yellow chair",
      },
    ],
    TROUSERS: [
      {
        id: "photo-1594633312681-425c7b97ccd1",
        alt: "Blush pink jogger trousers with strappy heels on white",
      },
      {
        id: "photo-1551854838-212c50b4c184",
        alt: "Woman in rust wide-leg trousers and a red sweater",
      },
      {
        id: "photo-1584273143981-41c073dfe8f8",
        alt: "Woman in a navy tailored suit with straight trousers",
      },
      {
        id: "photo-1566206091558-7f218b696731",
        alt: "Woman in white wide-leg trousers against a graffiti wall",
      },
    ],
    SHORTS: [
      {
        id: "photo-1591195853828-11db59a44f6b",
        alt: "Light wash distressed denim shorts on a white background",
      },
      {
        id: "photo-1598522325074-042db73aa4e6",
        alt: "Woman in grey drawstring shorts and a white t-shirt",
      },
      { id: "photo-1549062572-544a64fb0c56", alt: "Woman in a white blouse and denim shorts" },
    ],
    SHOES: [
      { id: "photo-1535043934128-cf0b28d52f95", alt: "Pair of nude pointed-toe stiletto pumps" },
      {
        id: "photo-1596703263926-eb0762ee17e4",
        alt: "Hand holding a black pointed pump against white",
      },
      {
        id: "photo-1515347619252-60a4bf4fff4f",
        alt: "Hand holding navy suede court heels outdoors",
      },
      {
        id: "photo-1531310197839-ccf54634509e",
        alt: "Woman wearing tan leather heeled ankle boots",
      },
      { id: "photo-1605733160314-4fc7dac4bb16", alt: "Pair of olive suede ankle boots on white" },
      {
        id: "photo-1727301209101-ef4f6f7048a3",
        alt: "Tan suede heeled ankle boots with jeans on an autumn street",
      },
      { id: "photo-1524635620932-ae4f58f5f3c1", alt: "Black leather buckle ankle boots on a road" },
      {
        id: "photo-1554062614-6da4fa67725a",
        alt: "Woman's legs in black stiletto heels against a wooden wall",
      },
    ],
  },
  CHILDREN: {
    TSHIRT: [
      {
        id: "photo-1622290291468-a28f7a7dc6a8",
        alt: "Kids' white t-shirt flat lay with a teddy bear and knit hat on pink",
      },
      { id: "photo-1471286174890-9c112ffca5b4", alt: "Smiling boy in a red t-shirt by the water" },
      {
        id: "photo-1627639679638-8485316a4b21",
        alt: "Toddler in a striped t-shirt and green trousers",
      },
      {
        id: "photo-1624728730423-9d6ec3aefcc0",
        alt: "Blond boy in a blue t-shirt against a white wooden wall",
      },
    ],
    HOODIE: [
      {
        id: "photo-1649006612249-6d32f5c2c429",
        alt: "Smiling boy in a grey zip hoodie with the hood up",
      },
      {
        id: "photo-1642768971292-73092d30b753",
        alt: "Boy in a purple and mustard colour-block hoodie",
      },
      {
        id: "photo-1519238263530-99bdd11df2ea",
        alt: "Smiling boy in a navy cardigan, bow tie and blue shorts",
      },
      {
        id: "photo-1541580621-cb65cc53084b",
        alt: "Boy in a green printed sweatshirt leaning on a tree",
      },
      {
        id: "photo-1619784299133-f691ffaea42f",
        alt: "Little girl in a brown knit sweater and knitted headband",
      },
    ],
    JACKET: [
      {
        id: "photo-1519457431-44ccd64a579b",
        alt: "Little girl in a light denim jacket against a blue wall",
      },
      {
        id: "photo-1503919005314-30d93d07d823",
        alt: "Boy in a tan jacket and cap feeding deer at a fence",
      },
      { id: "photo-1683035571579-2a74c8d33d63", alt: "Toddler in a red rain suit by a lake" },
      { id: "photo-1609147141924-7a3bc78b11fc", alt: "Toddler in a yellow hooded puffer snowsuit" },
      {
        id: "photo-1445796886651-d31a2c15f3c9",
        alt: "Toddler in a mustard coat and bobble hat walking through autumn leaves",
      },
      {
        id: "photo-1503919545889-aef636e10ad4",
        alt: "Child in a yellow raincoat with a backpack in a field",
      },
    ],
    TROUSERS: [
      {
        id: "photo-1698939096910-5b9a8fec3425",
        alt: "Toddler in striped denim overalls seen from behind",
      },
      { id: "photo-1555009393-f20bdb245c4d", alt: "Girl in denim overalls watering plants" },
      {
        id: "photo-1605713288447-9cecfb8d8c5a",
        alt: "Boy in blue jeans and a brown t-shirt in a meadow",
      },
      { id: "photo-1614690431089-afb0de81d184", alt: "Three children in jeans lying on the grass" },
      {
        id: "photo-1694026091737-10fdadf460ac",
        alt: "Toddler in a white t-shirt, brown trousers and colourful sneakers",
      },
      {
        id: "photo-1632337948797-ba161d29532b",
        alt: "Rust corduroy dungaree shorts hanging on a white radiator",
      },
    ],
    SHOES: [
      {
        id: "photo-1720019315435-b10b01792d9f",
        alt: "Pair of kids' chambray canvas lace-up sneakers on white",
      },
      {
        id: "photo-1540479859555-17af45c78602",
        alt: "Row of children in colourful rubber rain boots",
      },
      {
        id: "photo-1516658908390-30039e1d09d5",
        alt: "Child in red rain boots splashing in a puddle",
      },
    ],
  },
};

/** Product types without dedicated photos fall back to a related bucket. */
const FALLBACK: Partial<Record<ProductType, ProductType>> = {
  JEANS: "TROUSERS",
  SHIRT: "TSHIRT",
  SHORTS: "TROUSERS",
};

export function unsplashUrl(id: string, width = 1200): string {
  return `https://images.unsplash.com/${id}?auto=format&fit=crop&w=${width}&q=80`;
}

/**
 * Picks `imageCount` photos for a product. `siblingIndex` is the product's position among
 * products sharing the same bucket, so each one gets a different lead image.
 */
export function imagesFor(
  product: SeedProduct,
  siblingIndex: number,
): { url: string; alt: string }[] {
  const byCategory = PHOTOS[product.category];
  const fallback = FALLBACK[product.productType];
  const bucket =
    byCategory[product.productType] ?? (fallback ? byCategory[fallback] : undefined) ?? [];
  if (bucket.length === 0) {
    throw new Error(`No seed photos for ${product.category}/${product.productType}`);
  }
  const count = Math.min(product.imageCount, bucket.length);
  const offset = siblingIndex * count;
  return Array.from({ length: count }, (_, i) => bucket[(offset + i) % bucket.length])
    .filter((photo): photo is SeedPhoto => photo !== undefined)
    .map((photo) => ({ url: unsplashUrl(photo.id), alt: photo.alt }));
}
