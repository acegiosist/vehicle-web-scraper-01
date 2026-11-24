"use client";

import { useRouter } from "next/navigation";

import { NativeSelect } from "@/components/ui/native-select";

interface Props {
  size: number;
  /** One option per size, with the link that shows the grid at that size (page 1). */
  options: { size: number; href: string }[];
}

export function PageSizeSelect({ size, options }: Props) {
  const router = useRouter();
  return (
    <label className="flex items-center gap-2 text-sm text-muted-foreground">
      Filas por página
      <NativeSelect
        value={size}
        className="w-20"
        onChange={(e) => {
          const next = options.find((o) => o.size === Number(e.target.value));
          if (next) router.push(next.href);
        }}
      >
        {options.map((o) => (
          <option key={o.size} value={o.size}>
            {o.size}
          </option>
        ))}
      </NativeSelect>
    </label>
  );
}
