// The class strings that used to be element selectors in style.css: `input`,
// `button`, `th`, `td`, `pre`. Tailwind has no element layer, so a control
// that appears in ten places names its own look ten times -- unless the string
// lives once, here. Nothing in this file is a component and nothing imports
// React: it is text, so the Tailwind scanner sees every candidate.
//
// Anything used twice or less stays inline at its call site. A constant per
// one-off is the CSS file back again, with worse names.

const FOCUS =
  "focus:outline-none focus:border-accent focus:ring-3 focus:ring-accent/25";
const FOCUS_BTN =
  "focus-visible:outline-none focus-visible:border-accent focus-visible:ring-3 focus-visible:ring-accent/25";
const DISABLED = "disabled:opacity-50 disabled:cursor-not-allowed";

/** Text fields. Mono, because everything typed here is a url, JSON or code. */
export const INPUT =
  "w-full bg-surface-2 text-text border border-border rounded-md p-3 " +
  "font-mono text-[13px] leading-[1.6] transition duration-120 " +
  "aria-[invalid=true]:border-failed " +
  FOCUS;

export const TEXTAREA = INPUT + " block resize-y";
export const SELECT = INPUT + " font-ui cursor-pointer";

/** The one filled button: submit, and Run all. */
export const BTN =
  "bg-accent text-white border border-transparent rounded-md px-[18px] py-2.5 " +
  "font-ui text-sm font-semibold whitespace-nowrap cursor-pointer transition duration-120 " +
  "enabled:hover:bg-accent-hi enabled:active:translate-y-px " +
  DISABLED +
  " " +
  FOCUS_BTN;

/** Everything else. Reads as a control, weighs nothing next to the real one. */
export const GHOST =
  "bg-transparent text-dim border border-border-hi rounded-md px-3 py-1 " +
  "font-ui text-xs font-semibold whitespace-nowrap cursor-pointer transition duration-120 " +
  "enabled:hover:bg-surface-2 enabled:hover:text-text " +
  DISABLED +
  " " +
  FOCUS_BTN;

/** A joined pair: two options, both named, one pressed. Theme, and Fields/JSON. */
export const SEG = "flex";
export const SEG_BTN =
  "bg-transparent text-dim border border-border-hi px-3 py-1 " +
  "font-ui text-xs font-semibold cursor-pointer transition duration-120 " +
  "first:rounded-l-md last:rounded-r-md last:-ml-px " +
  "aria-[pressed=false]:hover:bg-surface-2 aria-[pressed=false]:hover:text-text " +
  // Pressed paints over the neighbour's edge, so the accent outlines all four sides.
  "aria-pressed:relative aria-pressed:bg-accent/12 aria-pressed:border-accent aria-pressed:text-text " +
  FOCUS_BTN;

/* --- containers -------------------------------------------------------- */

/** Every page is this box. `narrow` is the form page, which is one column.
 *  1600, not 1240: the two pages that use this one are wide data tables, and
 *  at a text column's width their url cells clip after twenty characters. */
export const MAIN = "mx-auto max-w-[1600px] px-4 pt-8 pb-12";
export const MAIN_NARROW = "mx-auto max-w-[860px] px-4 pt-8 pb-12";

export const CARD = "bg-surface border border-border rounded-lg p-6 mb-6";
export const CARD_HEAD = "flex flex-wrap items-center justify-between gap-3 mb-6";
export const HEAD_ACTIONS = "inline-flex flex-wrap items-center gap-3";
export const H1 = "text-xl font-semibold tracking-[-.01em]";
export const LABEL =
  "text-xs font-semibold tracking-[.06em] uppercase text-mute";
export const HINT = "text-xs text-mute";
/** Validation, under the row that caused it. */
export const ISSUE = "mt-1 mb-0 text-xs text-failed";
export const FIELD = "mb-6";
export const FIELD_LABEL = "block mb-2 text-dim";

/* --- tables ------------------------------------------------------------ */

/** Under md a table stops being a grid and becomes a list of cards: one card
 *  per row, one labelled line per cell. The header is hidden there, so the
 *  label has to travel on the cell -- every td carries `data-label` and the
 *  ::before prints it. All of it is descendant selectors on this one class, so
 *  no row or cell anywhere names a second class for the small screen.
 *  `w-auto!` is what cancels the fixed column widths, which mean nothing once
 *  a cell is a line rather than a column. */
const CARDS =
  "max-md:block " +
  "max-md:[&_thead]:hidden max-md:[&_tbody]:block " +
  "max-md:[&_tr]:mb-3 max-md:[&_tr]:block max-md:[&_tr]:rounded-lg " +
  "max-md:[&_tr]:border max-md:[&_tr]:border-border max-md:[&_tr]:p-2 " +
  "max-md:[&_td]:flex max-md:[&_td]:gap-3 max-md:[&_td]:border-0 " +
  "max-md:[&_td]:px-2 max-md:[&_td]:py-1 max-md:[&_td]:w-auto! " +
  "max-md:[&_td]:whitespace-normal! max-md:[&_td]:overflow-visible! max-md:[&_td]:break-words " +
  "max-md:[&_td[data-label]]:before:content-[attr(data-label)] " +
  "max-md:[&_td[data-label]]:before:w-24 max-md:[&_td[data-label]]:before:shrink-0 " +
  "max-md:[&_td[data-label]]:before:font-ui max-md:[&_td[data-label]]:before:text-[11px] " +
  "max-md:[&_td[data-label]]:before:uppercase max-md:[&_td[data-label]]:before:tracking-[.06em] " +
  "max-md:[&_td[data-label]]:before:leading-[1.7] max-md:[&_td[data-label]]:before:text-mute";

export const TABLE = "w-full border-collapse font-mono text-[13px] " + CARDS;
/** Last row's border would double up with the .scroll container's own. */
export const TBODY = "[&>tr:last-child>td]:border-b-0";
export const TH =
  "text-left font-ui text-xs font-semibold leading-[1.4] tracking-[.06em] " +
  "uppercase text-mute p-3 border-b border-border whitespace-nowrap";
export const TD = "p-3 border-b border-border align-top";

/** Fixed layout: every column with a natural size declares it below, and the
 *  truncated ones split what is left. Under auto layout a long url ignores
 *  `truncate`, takes the space it wants, and pushes Created off the edge. */
export const PICKS = TABLE + " md:table-fixed";
export const W = {
  id: "w-24",
  name: "w-[180px]",
  status: "w-[100px]",
  tag: "w-[100px]",
  num: "w-[90px]",
  when: "w-[172px] whitespace-nowrap",
  co: "w-[200px]",
  outcome: "w-[112px]",   // a status pill; the reason is on hover and in Details
  drop: "w-[44px]",
};

/** Digits right-align. Important, because TH already said text-left and two
 *  utilities for one property have no guaranteed order between them. */
export const NUM = "md:text-right!";

/** A name edited in place: the field is the display, so it carries no border
 *  until you reach for it. Anything heavier turns a table of names into a
 *  table of forms. The negative margin cancels this field's own padding, so a
 *  name sits on the same line as the plain text in the cells either side. */
export const NAME_INPUT =
  "font-mono text-[13px] leading-[1.6] text-text bg-transparent " +
  "border border-transparent rounded-md px-2 py-1 -my-[5px] " +
  "hover:border-border focus:bg-surface-2 " +
  "aria-[invalid=true]:border-failed " +
  FOCUS;

/* --- output ------------------------------------------------------------ */

export const PRE =
  "m-0 bg-surface-2 border border-border rounded-lg p-4 overflow-x-auto " +
  "max-h-[420px] font-mono text-[13px] leading-[1.6] text-text";

/** Verbatim, always -- never "something went wrong" (rules.md G28). */
export const ERROR =
  "m-0 bg-surface-2 border-l-[3px] border-failed rounded-r-md py-3 px-4 " +
  "font-mono text-[13px] leading-[1.6] text-text whitespace-pre-wrap break-words";

/** Empty and loading read the same shape, so a slow table does not jump. */
export const STATE =
  "py-12 px-4 text-center text-mute text-[13px] border border-border rounded-lg";

/** The border is the table's edge, and in card mode each card has its own. */
export const SCROLL =
  "overflow-x-auto border border-border rounded-lg max-md:rounded-none max-md:border-0";
export const SECTION = "mt-6";
/** The row of buttons above an expanded row's detail. */
export const ACTIONS = "mb-3 flex justify-end gap-3";
