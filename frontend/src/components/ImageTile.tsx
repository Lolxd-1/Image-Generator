/// components/ImageTile.tsx — square image thumbnail with an optional label
/// overlay, used for reference/dish images across Review/Generate/Catalog.
import { cn } from "../lib/cn";
import { imageUrl } from "../api/hooks";

export interface ImageTileProps {
  imageId: string | null | undefined;
  label?: string;
  onClick?: () => void;
  className?: string;
  size?: "sm" | "md" | "lg";
}

const SIZE: Record<NonNullable<ImageTileProps["size"]>, string> = {
  sm: "h-16 w-16",
  md: "h-28 w-28",
  lg: "h-44 w-44",
};

export function ImageTile({
  imageId,
  label,
  onClick,
  className,
  size = "md",
}: ImageTileProps) {
  const clickable = Boolean(onClick);
  return (
    <div
      role={clickable ? "button" : undefined}
      tabIndex={clickable ? 0 : undefined}
      onClick={onClick}
      onKeyDown={(e) => {
        if (clickable && (e.key === "Enter" || e.key === " ")) {
          e.preventDefault();
          onClick?.();
        }
      }}
      className={cn(
        "relative overflow-hidden rounded-md border border-base-700 bg-base-800",
        SIZE[size],
        clickable && "cursor-pointer transition-colors hover:border-accent-500",
        className,
      )}
    >
      {imageId ? (
        <img
          src={imageUrl(imageId)}
          alt={label ?? "item image"}
          className="h-full w-full object-cover"
          loading="lazy"
        />
      ) : (
        <div className="flex h-full w-full items-center justify-center text-[10px] uppercase tracking-wide text-base-500">
          No image
        </div>
      )}
      {label && (
        <span className="absolute inset-x-0 bottom-0 truncate bg-base-950/80 px-1.5 py-0.5 text-[10px] text-base-200">
          {label}
        </span>
      )}
    </div>
  );
}
