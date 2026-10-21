import "server-only";

import { prisma } from "@/lib/prisma";

export interface AddressDTO {
  id: string;
  fullName: string;
  phone: string;
  line1: string;
  line2: string | null;
  city: string;
  state: string;
  postalCode: string;
  country: string;
  isDefault: boolean;
}

/** The customer's addresses, default first. */
export async function getUserAddresses(userId: string): Promise<AddressDTO[]> {
  return prisma.address.findMany({
    where: { userId },
    orderBy: [{ isDefault: "desc" }, { createdAt: "desc" }],
    select: {
      id: true,
      fullName: true,
      phone: true,
      line1: true,
      line2: true,
      city: true,
      state: true,
      postalCode: true,
      country: true,
      isDefault: true,
    },
  });
}
