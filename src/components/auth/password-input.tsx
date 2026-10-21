"use client";

import { type InputHTMLAttributes, type Ref, useState } from "react";
import { HiOutlineEye, HiOutlineEyeSlash } from "react-icons/hi2";

import { Input } from "@/components/ui/input";

export function PasswordInput({
  ref,
  ...props
}: Omit<InputHTMLAttributes<HTMLInputElement>, "type"> & { ref?: Ref<HTMLInputElement> }) {
  const [visible, setVisible] = useState(false);
  return (
    <div className="relative">
      <Input ref={ref} type={visible ? "text" : "password"} className="pr-11" {...props} />
      <button
        type="button"
        onClick={() => setVisible((v) => !v)}
        className="absolute inset-y-0 right-0 flex w-11 items-center justify-center text-muted-foreground hover:text-foreground"
        aria-label={visible ? "Hide password" : "Show password"}
        aria-pressed={visible}
      >
        {visible ? (
          <HiOutlineEyeSlash aria-hidden="true" className="size-5" />
        ) : (
          <HiOutlineEye aria-hidden="true" className="size-5" />
        )}
      </button>
    </div>
  );
}
