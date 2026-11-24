import * as React from "react";
import { cn } from "cn";

/** A styled native <select>: works in plain GET forms and without JavaScript. */
function NativeSelect({ className, ...props }: React.ComponentProps<"select">) {
  return (
    <select
      data-slot="native-select"
      className={cn(
        "h-8 w-full min-w-0 rounded-lg border border-input bg-background px-2 py-1 text-sm transition-colors outline-none focus-visible:border-ring focus-visible:ring-3 focus-visible:ring-ring/50 disabled:cursor-not-allowed disabled:opacity-50 aria-invalid:border-destructive dark:bg-input/30",
        // the option list is drawn by the browser: give it the theme's colors explicitly
        "[&_option]:bg-popover [&_option]:text-popover-foreground",
        className,
      )}
      {...props}
    />
  );
}

export { NativeSelect };
