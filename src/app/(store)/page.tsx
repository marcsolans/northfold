import { STORE } from "@/lib/store-config";

export default function HomePage() {
  return (
    <div className="mx-auto flex max-w-3xl flex-1 flex-col justify-center px-6 py-24">
      <h1 className="text-4xl font-light tracking-tight">{STORE.name}</h1>
      <p className="mt-4 text-muted-foreground">{STORE.tagline}</p>
    </div>
  );
}
