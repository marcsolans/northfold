"use client";

import { type ReactNode } from "react";
import {
  type Control,
  type UseFormGetValues,
  type UseFormRegister,
  type UseFormSetValue,
  useFieldArray,
  useFormState,
} from "react-hook-form";
import { HiPlus, HiTrash } from "react-icons/hi2";

import { Button } from "@/components/ui/button";
import { Size } from "@/generated/prisma/enums";
import { suggestSku } from "@/lib/sku";
import { cn } from "@/lib/utils";
import type { ProductFormInput } from "@/lib/validators/product";

const SIZES = Object.values(Size);

/** Visible label on small screens (no column header there); screen-reader only on wider ones. */
function VariantField({
  id,
  label,
  index,
  children,
}: {
  id: string;
  label: string;
  index: number;
  children: ReactNode;
}) {
  return (
    <div className="space-y-1">
      <label htmlFor={id} className="text-xs text-muted-foreground md:sr-only">
        {label}
        <span className="sr-only"> of variant {index + 1}</span>
      </label>
      {children}
    </div>
  );
}

const cell =
  "h-10 w-full rounded-md border border-input bg-card px-2.5 text-sm focus-visible:border-foreground focus-visible:outline-none aria-invalid:border-destructive";

export function VariantsEditor({
  control,
  register,
  getValues,
  setValue,
  lockedVariantIds,
}: {
  control: Control<ProductFormInput>;
  register: UseFormRegister<ProductFormInput>;
  getValues: UseFormGetValues<ProductFormInput>;
  setValue: UseFormSetValue<ProductFormInput>;
  /** Variants that appear in orders: editable, but they cannot be removed. */
  lockedVariantIds: ReadonlySet<string>;
}) {
  const { fields, append, remove } = useFieldArray({ control, name: "variants" });
  const { errors } = useFormState({ control, name: "variants" });

  function addVariant() {
    const last = getValues("variants").at(-1);
    append({
      size: "M",
      colorName: last?.colorName ?? "",
      colorHex: last?.colorHex ?? "#1f1f1d",
      sku: "",
      stock: 0,
    });
  }

  function generateSku(index: number) {
    const variant = getValues(`variants.${index}`);
    setValue(
      `variants.${index}.sku`,
      suggestSku(getValues("slug"), variant.size, variant.colorName),
      {
        shouldDirty: true,
        shouldValidate: true,
      },
    );
  }

  const arrayError = errors.variants?.message ?? errors.variants?.root?.message;

  return (
    <div className="space-y-3">
      <div className="hidden grid-cols-[5rem_1fr_3.5rem_1.4fr_5.5rem_2.5rem] gap-2 px-1 text-xs font-medium text-muted-foreground md:grid">
        <span>Size</span>
        <span>Colour</span>
        <span>Hex</span>
        <span>SKU</span>
        <span>Stock</span>
        <span className="sr-only">Remove</span>
      </div>
      <ul className="space-y-3">
        {fields.map((field, index) => {
          const rowErrors = errors.variants?.[index];
          const variantId = getValues(`variants.${index}.id`);
          const locked = variantId !== undefined && lockedVariantIds.has(variantId);
          return (
            <li
              key={field.id}
              className="grid grid-cols-2 gap-2 rounded-lg border border-border p-3 md:grid-cols-[5rem_1fr_3.5rem_1.4fr_5.5rem_2.5rem] md:border-0 md:p-0"
            >
              <VariantField id={`v-size-${field.id}`} label="Size" index={index}>
                <select
                  id={`v-size-${field.id}`}
                  className={cell}
                  {...register(`variants.${index}.size`)}
                >
                  {SIZES.map((size) => (
                    <option key={size} value={size}>
                      {size}
                    </option>
                  ))}
                </select>
              </VariantField>
              <VariantField id={`v-color-${field.id}`} label="Colour" index={index}>
                <input
                  id={`v-color-${field.id}`}
                  placeholder="Colour"
                  className={cell}
                  aria-invalid={rowErrors?.colorName ? true : undefined}
                  {...register(`variants.${index}.colorName`)}
                />
              </VariantField>
              <VariantField id={`v-hex-${field.id}`} label="Swatch" index={index}>
                <input
                  id={`v-hex-${field.id}`}
                  type="color"
                  className="h-10 w-full cursor-pointer rounded-md border border-input bg-card p-1"
                  {...register(`variants.${index}.colorHex`)}
                />
              </VariantField>
              <VariantField id={`v-sku-${field.id}`} label="SKU" index={index}>
                <div className="flex gap-1">
                  <input
                    id={`v-sku-${field.id}`}
                    placeholder="SKU"
                    className={cn(cell, "uppercase")}
                    aria-invalid={rowErrors?.sku ? true : undefined}
                    {...register(`variants.${index}.sku`)}
                  />
                  <Button
                    variant="ghost"
                    size="sm"
                    className="h-10 px-2 text-xs"
                    onClick={() => generateSku(index)}
                  >
                    Auto
                  </Button>
                </div>
              </VariantField>
              <VariantField id={`v-stock-${field.id}`} label="Stock" index={index}>
                <input
                  id={`v-stock-${field.id}`}
                  inputMode="numeric"
                  className={cell}
                  aria-invalid={rowErrors?.stock ? true : undefined}
                  {...register(`variants.${index}.stock`)}
                />
              </VariantField>
              <Button
                variant="ghost"
                size="icon"
                className="self-end text-destructive"
                aria-label={
                  locked
                    ? `Variant ${index + 1} has orders and cannot be removed`
                    : `Remove variant ${index + 1}`
                }
                title={locked ? "This variant has orders — set its stock to 0 instead" : undefined}
                disabled={locked || fields.length === 1}
                onClick={() => remove(index)}
              >
                <HiTrash aria-hidden="true" className="size-4" />
              </Button>
              {rowErrors ? (
                <p role="alert" className="col-span-full text-xs text-destructive">
                  {rowErrors.colorName?.message ??
                    rowErrors.sku?.message ??
                    rowErrors.stock?.message ??
                    rowErrors.colorHex?.message}
                </p>
              ) : null}
            </li>
          );
        })}
      </ul>
      {arrayError ? (
        <p role="alert" className="text-xs text-destructive">
          {arrayError}
        </p>
      ) : null}
      <Button variant="outline" size="sm" onClick={addVariant}>
        <HiPlus aria-hidden="true" className="size-4" />
        Add variant
      </Button>
    </div>
  );
}
