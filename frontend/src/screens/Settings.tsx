/// screens/Settings.tsx — key pool + storage admin screen (T07): where the
/// operator manages the Gemini key pool and watches the storage budget.
import { Link } from "react-router-dom";
import { KeyPoolSection } from "./settings/KeyPoolSection";
import { StorageSection } from "./settings/StorageSection";

export default function Settings() {
  return (
    <div className="mx-auto max-w-5xl px-6 py-8">
      <div className="mb-6 flex items-center justify-between">
        <h1 className="text-lg font-semibold text-base-100">Settings</h1>
        <Link to="/" className="text-xs text-base-400 hover:text-base-100">
          Back to shops
        </Link>
      </div>
      <div className="flex flex-col gap-4">
        <KeyPoolSection />
        <StorageSection />
      </div>
    </div>
  );
}
