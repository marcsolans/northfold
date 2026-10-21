import { StoreShell } from "@/components/layout/store-shell";

export default function StoreLayout({ children }: LayoutProps<"/">) {
  return <StoreShell>{children}</StoreShell>;
}
