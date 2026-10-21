import { countryName } from "@/lib/countries";

export interface AddressLike {
  fullName: string;
  phone: string;
  line1: string;
  line2: string | null;
  city: string;
  state: string;
  postalCode: string;
  country: string;
}

export function AddressSummary({
  address,
  className,
}: {
  address: AddressLike;
  className?: string;
}) {
  return (
    <address className={className ?? "text-sm leading-relaxed text-muted-foreground not-italic"}>
      <span className="font-medium text-foreground">{address.fullName}</span>
      <br />
      {address.line1}
      {address.line2 ? (
        <>
          <br />
          {address.line2}
        </>
      ) : null}
      <br />
      {address.city}, {address.state} {address.postalCode}
      <br />
      {countryName(address.country)}
      <br />
      {address.phone}
    </address>
  );
}
