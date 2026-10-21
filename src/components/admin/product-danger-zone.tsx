"use client";

import { useRouter } from "next/navigation";
import { useState, useTransition } from "react";
import toast from "react-hot-toast";

import { Button } from "@/components/ui/button";
import { Card, CardContent, CardDescription, CardHeader, CardTitle } from "@/components/ui/card";
import { Modal } from "@/components/ui/modal";
import { deleteProduct } from "@/server/actions/admin/products";

export function ProductDangerZone({
  productId,
  hasOrders,
}: {
  productId: string;
  hasOrders: boolean;
}) {
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const [pending, startTransition] = useTransition();

  function confirmDelete() {
    startTransition(async () => {
      const result = await deleteProduct(productId);
      if (!result.ok) {
        toast.error(result.error);
        return;
      }
      toast.success("Product deleted");
      router.push("/admin/products");
    });
  }

  return (
    <Card className="border-destructive/30">
      <CardHeader>
        <CardTitle>Delete product</CardTitle>
        <CardDescription>
          {hasOrders
            ? "This product has been ordered, so it can’t be deleted — archive it instead to hide it from the store."
            : "Permanently removes the product, its variants and its uploaded images."}
        </CardDescription>
      </CardHeader>
      <CardContent>
        <Button variant="destructive" disabled={hasOrders} onClick={() => setOpen(true)}>
          Delete product
        </Button>
      </CardContent>
      <Modal
        open={open}
        onClose={() => setOpen(false)}
        title="Delete this product?"
        description="This cannot be undone."
        footer={
          <>
            <Button variant="ghost" onClick={() => setOpen(false)} disabled={pending}>
              Keep it
            </Button>
            <Button
              variant="destructive"
              onClick={confirmDelete}
              loading={pending}
              loadingText="Deleting…"
            >
              Delete permanently
            </Button>
          </>
        }
      />
    </Card>
  );
}
