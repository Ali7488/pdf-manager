/**
 * The options that differ between actions (F26, F28, F29, F30), plus the
 * shared "Use OCR" checkbox (F10).
 */
import { useState } from "react";
import { Action, type ActionSettings, type CompressLevel, type InputFile, type SplitMethod } from "../../api/types";
import { Checkbox } from "../../components/Field/Checkbox";
import { RadioCards, type RadioOption } from "../../components/Field/RadioCards";
import { TextField } from "../../components/Field/TextField";
import { getActionInfo } from "../../lib/actions";
import styles from "./ActionPage.module.css";
import { splitPageNote, splitProblem } from "./splitValidation";

/** Explanation shown by the (?) next to "Use OCR". */
export const OCR_TIP = "Reads the text in page images so you can search and copy it. Slower.";
/** Explanation shown by the (?) next to "Add a contents page". */
export const CONTENTS_TIP = "Adds a first page listing each file with clickable links.";

/** Props for {@link ActionOptions}. */
export interface ActionOptionsProps {
  action: Action;
  settings: ActionSettings;
  onChange(patch: Partial<ActionSettings>): void;
  /** Files the job will use (for the Split page-count note). */
  usedFiles: InputFile[];
}

/** Renders the options for one action. */
export function ActionOptions({ action, settings, onChange, usedFiles }: ActionOptionsProps) {
  const info = getActionInfo(action);
  return (
    <>
      {info.merges && (
        <Checkbox
          label="Add a contents page"
          detail="A first page listing each file, with links that jump to it."
          tip={CONTENTS_TIP}
          checked={settings.contentsPage}
          onChange={(contentsPage) => onChange({ contentsPage })}
        />
      )}
      {action === Action.Split && (
        <SplitOptions split={settings.split} onChange={(split) => onChange({ split })} usedFiles={usedFiles} />
      )}
      {action === Action.ImagesToPdf && (
        <RadioCards
          legend="What to make"
          options={IMAGE_OPTIONS}
          value={settings.combineImages ? "combine" : "separate"}
          onChange={(value) => onChange({ combineImages: value === "combine" })}
        />
      )}
      {action === Action.Compress && (
        <RadioCards
          legend="How much to compress"
          options={COMPRESS_OPTIONS}
          value={settings.compressLevel}
          onChange={(compressLevel) => onChange({ compressLevel })}
        />
      )}
      {info.offersOcr && (
        <Checkbox
          label="Use OCR"
          detail="Makes the text in your pages searchable and copyable. Takes longer."
          tip={OCR_TIP}
          checked={settings.useOcr}
          onChange={(useOcr) => onChange({ useOcr })}
        />
      )}
    </>
  );
}

const IMAGE_OPTIONS: readonly RadioOption<"combine" | "separate">[] = [
  { value: "combine", label: "One PDF with all images", hint: "Each image becomes a page, in the order of the list." },
  { value: "separate", label: "One PDF per image", hint: "Each image becomes its own PDF file." },
];

const COMPRESS_OPTIONS: readonly RadioOption<CompressLevel>[] = [
  {
    value: "light",
    label: "Light",
    hint: "Same quality, a little smaller.",
    tip: "Keeps the quality almost the same. The file gets a little smaller.",
  },
  {
    value: "balanced",
    label: "Balanced",
    hint: "Much smaller, still sharp. Best for most files.",
    tip: "Noticeably smaller, and pictures still look sharp. A good choice for most files.",
  },
  {
    value: "strong",
    label: "Strong",
    hint: "Smallest file; pictures may look soft up close.",
    tip: "Makes the file as small as possible. Pictures may look blurry or blocky up close.",
  },
];

const SPLIT_OPTIONS: readonly RadioOption<SplitMethod>[] = [
  { value: "ranges", label: "Pages I choose", hint: "Type ranges like 1-3, 5. Each range becomes a file." },
  { value: "every_n", label: "Every few pages", hint: "Cuts the file into parts of the same size." },
  { value: "per_page", label: "One file per page", hint: "Every page becomes its own PDF." },
];

const SPLIT_TIP =
  "Each range becomes its own PDF file. For example, 1-3, 5 makes two files: one with pages 1 to 3, and one with page 5.";

interface SplitOptionsProps {
  split: ActionSettings["split"];
  onChange(split: ActionSettings["split"]): void;
  usedFiles: InputFile[];
}

/**
 * Split method and its input. The range error appears once the user has
 * typed something, so an empty box isn't shown as an error straight away.
 */
function SplitOptions({ split, onChange, usedFiles }: SplitOptionsProps) {
  const [touched, setTouched] = useState(split.ranges !== "");
  const problem = splitProblem(split);
  const note = splitPageNote(split, usedFiles);

  return (
    <RadioCards
      legend="How to split"
      legendTip={SPLIT_TIP}
      options={SPLIT_OPTIONS}
      value={split.method}
      onChange={(method) => onChange({ ...split, method })}
    >
      <div className={styles.splitInput}>
        {split.method === "ranges" && (
          <TextField
            label="Pages"
            placeholder="1-3, 5, 8-10"
            value={split.ranges}
            onChange={(event) => {
              setTouched(true);
              onChange({ ...split, ranges: event.target.value });
            }}
            onBlur={() => setTouched(true)}
            error={touched ? problem : null}
            help={note ?? "Separate pages and ranges with commas."}
          />
        )}
        {split.method === "every_n" && (
          <TextField
            label="Pages in each file"
            type="number"
            min={1}
            step={1}
            value={Number.isNaN(split.everyN) ? "" : split.everyN}
            onChange={(event) => onChange({ ...split, everyN: event.target.value === "" ? NaN : Number(event.target.value) })}
            error={problem}
            suffix="pages"
          />
        )}
      </div>
    </RadioCards>
  );
}
