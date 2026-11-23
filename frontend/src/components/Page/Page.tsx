/**
 * Building blocks shared by the pages: a header and a card-like section.
 */
import type { ReactNode } from "react";
import { InfoTip } from "../InfoTip/InfoTip";
import styles from "./Page.module.css";

/** Props for {@link PageHeader}. */
export interface PageHeaderProps {
  title: string;
  /** At most one short instruction or status line under the title (no decorative subtitles). */
  description?: ReactNode;
  /** Optional explanation shown in a (?) tooltip beside the title. */
  tip?: string;
}

/** The page title (the only <h1> on a page) and its description. */
export function PageHeader({ title, description, tip }: PageHeaderProps) {
  return (
    <header className={styles.header}>
      <div className={styles.titleRow}>
        <h1 className={styles.title}>{title}</h1>
        {tip && <InfoTip label={title} text={tip} />}
      </div>
      {description && <p className={styles.description}>{description}</p>}
    </header>
  );
}

/** Props for {@link Section}. */
export interface SectionProps {
  /** Section heading (an <h2>). */
  title?: string;
  /** Optional element beside the title, such as a (?) tip. */
  titleExtra?: ReactNode;
  children: ReactNode;
}

/** A rounded panel grouping related controls. */
export function Section({ title, titleExtra, children }: SectionProps) {
  return (
    <section className={styles.section} aria-label={title}>
      {title && (
        <div className={styles.sectionHeading}>
          <h2 className={styles.sectionTitle}>{title}</h2>
          {titleExtra}
        </div>
      )}
      {children}
    </section>
  );
}
