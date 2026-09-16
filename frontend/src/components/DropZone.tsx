/// components/DropZone.tsx — drag-and-drop (or click-to-browse) file input.
import { useCallback, useRef, useState } from "react";
import type { DragEvent, ChangeEvent } from "react";
import { cn } from "../lib/cn";

export interface DropZoneProps {
  onFiles: (files: File[]) => void;
  accept?: string;
  multiple?: boolean;
  label?: string;
  hint?: string;
  className?: string;
  disabled?: boolean;
}

export function DropZone({
  onFiles,
  accept,
  multiple = true,
  label = "Drop files here, or click to browse",
  hint,
  className,
  disabled,
}: DropZoneProps) {
  const [dragging, setDragging] = useState(false);
  const inputRef = useRef<HTMLInputElement>(null);

  const handleFiles = useCallback(
    (fileList: FileList | null) => {
      if (!fileList || fileList.length === 0) return;
      onFiles(Array.from(fileList));
    },
    [onFiles],
  );

  const onDrop = useCallback(
    (e: DragEvent<HTMLDivElement>) => {
      e.preventDefault();
      setDragging(false);
      if (disabled) return;
      handleFiles(e.dataTransfer.files);
    },
    [disabled, handleFiles],
  );

  const onChange = useCallback(
    (e: ChangeEvent<HTMLInputElement>) => {
      handleFiles(e.target.files);
      e.target.value = "";
    },
    [handleFiles],
  );

  return (
    <div
      role="button"
      tabIndex={disabled ? -1 : 0}
      onClick={() => !disabled && inputRef.current?.click()}
      onKeyDown={(e) => {
        if (!disabled && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          inputRef.current?.click();
        }
      }}
      onDragOver={(e) => {
        e.preventDefault();
        if (!disabled) setDragging(true);
      }}
      onDragLeave={() => setDragging(false)}
      onDrop={onDrop}
      className={cn(
        "flex flex-col items-center justify-center gap-1 rounded-lg border-2 border-dashed px-4 py-8 text-center transition-colors",
        disabled
          ? "cursor-not-allowed border-base-700 opacity-50"
          : "cursor-pointer border-base-600 hover:border-accent-500",
        dragging && "border-accent-500 bg-accent-600/5",
        className,
      )}
    >
      <span className="text-sm text-base-200">{label}</span>
      {hint && <span className="text-xs text-base-400">{hint}</span>}
      <input
        ref={inputRef}
        type="file"
        accept={accept}
        multiple={multiple}
        disabled={disabled}
        onChange={onChange}
        className="hidden"
      />
    </div>
  );
}
