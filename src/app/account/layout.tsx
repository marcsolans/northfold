import { StoreShell } from "@/components/layout/store-shell";

export default function AccountLayout({ children }: LayoutProps<"/account">) {
  return <StoreShell>{children}</StoreShell>;
}
