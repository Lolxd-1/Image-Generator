/// screens/setup/OtherSelect.tsx — a Select seeded with sensible options
/// plus a free-text "Other" fallback, used for each of the 7 shop context
/// metrics (SPEC.md §2: plain nullable strings on Shop).
import { useState } from "react";
import { Input } from "../../components/Input";
import { Select } from "../../components/Select";

const OTHER = "__other__";

export interface OtherSelectProps {
  label: string;
  hint?: string;
  options: string[];
  value: string | null;
  onChange: (value: string | null) => void;
}

export function OtherSelect({ label, hint, options, value, onChange }: OtherSelectProps) {
  const isKnown = value === null || value === "" || options.includes(value);
  const [showOther, setShowOther] = useState(!isKnown);

  const selectValue = showOther ? OTHER : value ?? "";

  return (
    <div className="flex flex-col gap-1.5">
      <Select
        label={label}
        placeholder="Select..."
        value={selectValue}
        options={[
          ...options.map((o) => ({ value: o, label: o })),
          { value: OTHER, label: "Other..." },
        ]}
        onChange={(e) => {
          const next = e.target.value;
          if (next === OTHER) {
            setShowOther(true);
            return;
          }
          setShowOther(false);
          onChange(next || null);
        }}
      />
      {!showOther && hint && <span className="text-xs text-base-400">{hint}</span>}
      {showOther && (
        <Input
          placeholder="Describe it"
          hint={hint}
          value={value ?? ""}
          onChange={(e) => onChange(e.target.value || null)}
          autoFocus
        />
      )}
    </div>
  );
}
