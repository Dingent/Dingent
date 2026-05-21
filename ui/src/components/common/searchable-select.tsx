import * as React from "react";
import { Check, ChevronsUpDown } from "lucide-react";
import { twMerge } from "tailwind-merge";
import { Popover, PopoverContent, PopoverTrigger } from "../ui/popover";
import { Button } from "../ui/button";
import {
  Command,
  CommandEmpty,
  CommandGroup,
  CommandInput,
  CommandItem,
  CommandList,
} from "../ui/command";

// 1. Define a more explicit type for the options
type Option = { label: string; value: string };
type SearchableSelectProps = {
  options: string[] | Option[];
  value?: string;
  onChange: (value: string) => void;
  placeholder?: string;
  emptyText?: string;
  className?: string;
};

export function SearchableSelect({
  options,
  value,
  onChange,
  placeholder = "Select...",
  emptyText = "No results.",
  className,
}: SearchableSelectProps) {
  const [open, setOpen] = React.useState(false);

  // 2. Normalize options to a consistent format internally
  // This allows the rest of the component to work with a single data structure
  const normalizedOptions: Option[] = React.useMemo(() => {
    if (!options.length) return [];
    // Check the type of the first element to determine the format
    if (typeof options[0] === "string") {
      return (options as string[]).map((opt) => ({ label: opt, value: opt }));
    }
    return options as Option[];
  }, [options]);

  // 3. Find the display label for the currently selected value
  const displayLabel =
    normalizedOptions.find((opt) => opt.value === value)?.label || placeholder;

  return (
    <Popover open={open} onOpenChange={setOpen}>
      <PopoverTrigger asChild>
        <Button
          variant="outline"
          role="combobox"
          aria-expanded={open}
          className={twMerge("w-full justify-between", className)}
        >
          <span className="truncate">{displayLabel}</span>
          <ChevronsUpDown className="ml-2 h-4 w-4 shrink-0 opacity-50" />
        </Button>
      </PopoverTrigger>
      <PopoverContent className="w-[var(--radix-popover-trigger-width)] p-0">
        <Command>
          <CommandInput placeholder="Search..." />
          <CommandList>
            {" "}
            {/* Use CommandList for scrolling long lists */}
            <CommandEmpty>{emptyText}</CommandEmpty>
            <CommandGroup>
              {/* 4. Map over the normalized options */}
              {normalizedOptions.map((opt) => (
                <CommandItem
                  key={opt.value}
                  value={opt.label} // Search by label
                  onSelect={() => {
                    // On select, call onChange with the actual value
                    onChange(opt.value);
                    setOpen(false);
                  }}
                >
                  <Check
                    className={twMerge(
                      "mr-2 h-4 w-4",
                      // Compare with the option's value
                      value === opt.value ? "opacity-100" : "opacity-0",
                    )}
                  />
                  {/* Display the option's label */}
                  {opt.label}
                </CommandItem>
              ))}
            </CommandGroup>
          </CommandList>
        </Command>
      </PopoverContent>
    </Popover>
  );
}
