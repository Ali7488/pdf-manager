/**
 * The shared file list: drag to reorder, remove one, or clear all. The same
 * list is shown on Home and on every action tab.
 */
import {
  DndContext,
  KeyboardSensor,
  PointerSensor,
  closestCenter,
  useSensor,
  useSensors,
  type Announcements,
  type DragEndEvent,
  type Modifier,
} from "@dnd-kit/core";
import {
  SortableContext,
  sortableKeyboardCoordinates,
  useSortable,
  verticalListSortingStrategy,
} from "@dnd-kit/sortable";
import { CSS } from "@dnd-kit/utilities";
import type { ReactNode } from "react";
import type { Action, InputFile } from "../../api/types";
import { actionAcceptsFile } from "../../lib/actions";
import { formatBytes, formatPages, kindLabel } from "../../lib/format";
import { useApp } from "../../state/AppContext";
import { Button } from "../Button/Button";
import { Icon } from "../Icon/Icon";
import { InfoTip } from "../InfoTip/InfoTip";
import styles from "./FileList.module.css";

/** Props for {@link FileList}. */
export interface FileListProps {
  /**
   * The tab's action. Files it doesn't accept are greyed with a short note and
   * left out of the job. Leave out on Home, where every file is shown normally.
   */
  action?: Action;
  /** Extra buttons for the header, such as "Add files". */
  headerActions?: ReactNode;
}

/** Keeps dragged rows moving straight up and down. */
const restrictToVerticalAxis: Modifier = ({ transform }) => ({ ...transform, x: 0 });

const ORDER_TIP =
  "Files are used from top to bottom. When merging, this is the order of the pages in the result. Drag a file by its handle to move it.";

/**
 * Renders the shared list from app state. Reordering works with the mouse
 * (drag the handle) and the keyboard (focus the handle, press Space, use the
 * arrow keys, press Space again).
 */
export function FileList({ action, headerActions }: FileListProps) {
  const { state, dispatch } = useApp();
  const files = state.files;
  const sensors = useSensors(
    useSensor(PointerSensor, { activationConstraint: { distance: 4 } }),
    useSensor(KeyboardSensor, { coordinateGetter: sortableKeyboardCoordinates }),
  );

  const nameOf = (id: string | number) => files.find((file) => file.path === id)?.name ?? "the file";
  const positionOf = (id: string | number) => files.findIndex((file) => file.path === id) + 1;
  const announcements: Announcements = {
    onDragStart: ({ active }) => `Picked up ${nameOf(active.id)}.`,
    onDragOver: ({ active, over }) =>
      over ? `${nameOf(active.id)} is now at position ${positionOf(over.id)} of ${files.length}.` : undefined,
    onDragEnd: ({ active, over }) =>
      over ? `${nameOf(active.id)} was dropped at position ${positionOf(over.id)} of ${files.length}.` : undefined,
    onDragCancel: ({ active }) => `Moving ${nameOf(active.id)} was cancelled.`,
  };

  const onDragEnd = ({ active, over }: DragEndEvent) => {
    if (over && active.id !== over.id) {
      dispatch({ type: "fileMoved", fromPath: String(active.id), toPath: String(over.id) });
    }
  };

  const usedCount = action ? files.filter((file) => actionAcceptsFile(action, file)).length : files.length;

  return (
    <section className={styles.panel} aria-label="Files">
      <header className={styles.header}>
        <div className={styles.headerTitle}>
          <h2 className={styles.title}>Files</h2>
          <InfoTip label="file order" text={ORDER_TIP} />
          {files.length > 0 && (
            <span className={styles.count}>
              {action && usedCount !== files.length
                ? `${usedCount} of ${files.length} used here`
                : files.length === 1
                  ? "1 file"
                  : `${files.length} files`}
            </span>
          )}
        </div>
        <div className={styles.headerActions}>
          {files.length > 0 && (
            <Button size="sm" variant="ghost" onClick={() => dispatch({ type: "filesCleared" })}>
              Clear all
            </Button>
          )}
          {headerActions}
        </div>
      </header>

      {files.length === 0 ? (
        <p className={styles.empty}>No files yet. Drop files anywhere in this window, or use Add files.</p>
      ) : (
        <DndContext
          sensors={sensors}
          collisionDetection={closestCenter}
          modifiers={[restrictToVerticalAxis]}
          onDragEnd={onDragEnd}
          accessibility={{
            announcements,
            screenReaderInstructions: {
              draggable:
                "To move a file, press Space, then use the up and down arrow keys. Press Space again to drop it, or Escape to cancel.",
            },
          }}
        >
          <SortableContext items={files.map((file) => file.path)} strategy={verticalListSortingStrategy}>
            <ol className={styles.list}>
              {files.map((file, index) => (
                <FileRow
                  key={file.path}
                  file={file}
                  position={index + 1}
                  applicable={action ? actionAcceptsFile(action, file) : true}
                  onRemove={() => dispatch({ type: "fileRemoved", path: file.path })}
                />
              ))}
            </ol>
          </SortableContext>
        </DndContext>
      )}
    </section>
  );
}

interface FileRowProps {
  file: InputFile;
  position: number;
  applicable: boolean;
  onRemove(): void;
}

/** One sortable row: handle, details, remove button. */
function FileRow({ file, position, applicable, onRemove }: FileRowProps) {
  const { api } = useApp();
  const { attributes, listeners, setNodeRef, setActivatorNodeRef, transform, transition, isDragging } = useSortable({
    id: file.path,
  });
  const details = [kindLabel(file.kind), formatBytes(file.sizeBytes)];
  if (file.pageCount !== null) details.push(formatPages(file.pageCount));

  const classes = [styles.row, applicable ? "" : styles.notApplicable, isDragging ? styles.dragging : ""]
    .filter(Boolean)
    .join(" ");

  return (
    <li
      ref={setNodeRef}
      className={classes}
      style={{ transform: CSS.Translate.toString(transform), transition }}
      data-testid="file-row"
      data-applicable={applicable}
    >
      <button
        ref={setActivatorNodeRef}
        type="button"
        className={styles.handle}
        aria-label={`Move ${file.name} (position ${position})`}
        {...attributes}
        {...listeners}
      >
        <Icon name="grip" />
      </button>
      <span className={styles.kind} aria-hidden="true">
        <Icon name={file.kind === "image" ? "image" : "file"} size={18} />
      </span>
      <div className={styles.info}>
        {/* Browser mode's `path` is an ID, not a path: show the name instead. */}
        <span className={styles.name} title={api.mode === "browser" ? file.name : file.path}>
          {file.name}
        </span>
        <span className={styles.meta}>
          {details.join(" · ")}
          {!applicable && <span className={styles.note}> · Not used in this mode</span>}
        </span>
      </div>
      <button type="button" className={styles.remove} aria-label={`Remove ${file.name}`} onClick={onRemove}>
        <Icon name="close" size={16} />
      </button>
    </li>
  );
}
