/**
 * Opens the native file picker and adds the chosen files to the shared list.
 */
import { useState } from "react";
import { useApp } from "../../state/AppContext";
import { Button, type ButtonProps } from "../Button/Button";

/** Props for {@link AddFilesButton}. */
export interface AddFilesButtonProps extends Pick<ButtonProps, "variant" | "size"> {
  /** "all" for every supported type, "documents" for PDF and PowerPoint, "images" for PNG and JPG. */
  kind: "all" | "documents" | "images";
  /** Button text. Defaults to "Add images" for images, otherwise "Add files". */
  label?: string;
}

/**
 * Calls `pickFiles(kind)`; files already in the list are skipped by the
 * reducer. A cancelled picker returns no files and changes nothing.
 */
export function AddFilesButton({ kind, label, variant = "secondary", size = "md" }: AddFilesButtonProps) {
  const { api, dispatch } = useApp();
  const [busy, setBusy] = useState(false);

  const pick = async () => {
    setBusy(true);
    try {
      const files = await api.pickFiles(kind);
      if (files.length > 0) dispatch({ type: "filesAdded", files });
    } finally {
      setBusy(false);
    }
  };

  return (
    <Button variant={variant} size={size} icon={kind === "images" ? "image" : "plus"} onClick={pick} disabled={busy}>
      {label ?? (kind === "images" ? "Add images" : "Add files")}
    </Button>
  );
}
