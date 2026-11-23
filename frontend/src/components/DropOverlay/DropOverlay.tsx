/**
 * Makes the whole window a drop target for files and shows a clear overlay
 * while files are dragged over it.
 */
import { useEffect, useState } from "react";
import { useApp } from "../../state/AppContext";
import { Icon } from "../Icon/Icon";
import styles from "./DropOverlay.module.css";

/** True if a drag carries files (not text, links or a list row). */
function hasFiles(event: DragEvent): boolean {
  return Array.from(event.dataTransfer?.types ?? []).includes("Files");
}

/**
 * Listens on `window` for file drags.
 *
 * It calls `preventDefault()` on `dragover` and `drop` so the window doesn't
 * navigate to the file, then hands the files to `addDroppedFiles`. In the
 * desktop app, Python reads the real paths from the drop itself and sends
 * `filesAdded` (so that returns nothing). Browser mode uploads them to the app
 * as working copies; the dev mock turns them into fake files.
 */
export function DropOverlay() {
  const { api, dispatch } = useApp();
  const [dragging, setDragging] = useState(false);

  useEffect(() => {
    // dragenter/dragleave fire for every child element, so count them.
    let depth = 0;
    const onEnter = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth += 1;
      setDragging(true);
    };
    const onOver = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      if (event.dataTransfer) event.dataTransfer.dropEffect = "copy";
    };
    const onLeave = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      depth = Math.max(0, depth - 1);
      if (depth === 0) setDragging(false);
    };
    const onDrop = (event: DragEvent) => {
      if (!hasFiles(event)) return;
      event.preventDefault();
      depth = 0;
      setDragging(false);
      const files = Array.from(event.dataTransfer?.files ?? []);
      if (files.length === 0) return;
      api.addDroppedFiles(files).then(
        (added) => {
          if (added.length > 0) dispatch({ type: "filesAdded", files: added });
        },
        () => undefined, // Browser mode reports a lost connection itself.
      );
    };
    window.addEventListener("dragenter", onEnter);
    window.addEventListener("dragover", onOver);
    window.addEventListener("dragleave", onLeave);
    window.addEventListener("drop", onDrop);
    return () => {
      window.removeEventListener("dragenter", onEnter);
      window.removeEventListener("dragover", onOver);
      window.removeEventListener("dragleave", onLeave);
      window.removeEventListener("drop", onDrop);
    };
  }, [api, dispatch]);

  return (
    <div className={`${styles.overlay} ${dragging ? styles.active : ""}`} aria-hidden={!dragging}>
      <div className={styles.card}>
        <Icon name="upload" size={40} />
        <p className={styles.title}>Drop to add your files</p>
      </div>
    </div>
  );
}
