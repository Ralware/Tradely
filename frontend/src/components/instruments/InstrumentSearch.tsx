import { useCallback, useEffect, useId, useLayoutEffect, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useInstrumentSearch } from '../../hooks/useInstrumentSearch';
import { instrumentService } from '../../services/instrumentService';
import type { Instrument, InstrumentCandidate } from '../../types/api';
import { cn } from '../../utils/format';
import { Icon } from '../common/Icon';

type SelectableInstrument = Instrument | InstrumentCandidate;

function marketLabel(instrument: Pick<Instrument, 'market' | 'asset_type'>): string {
  if (instrument.asset_type === 'crypto') return 'Crypto';
  return instrument.market === 'india' ? 'India' : 'Global';
}

export function InstrumentSearch({
  value,
  placeholder = 'Search Ticker Or Name',
  onSelect,
  onQueryEdit,
  className,
  inputClassName,
  autoFocus = false,
  disabled = false,
  clearOnSelect = false,
}: {
  value?: string;
  placeholder?: string;
  onQueryEdit?: () => void;
  onSelect: (instrument: Instrument) => void;
  className?: string;
  inputClassName?: string;
  autoFocus?: boolean;
  disabled?: boolean;
  clearOnSelect?: boolean;
}) {
  const [query, setQuery] = useState(value ?? '');
  const listboxId = useId();
  const [open, setOpen] = useState(false);
  const search = useInstrumentSearch(query, open && !disabled);
  const selectionRequest = useRef<AbortController | null>(null);
  const [resolutionError, setResolutionError] = useState<string | null>(null);
  const [selecting, setSelecting] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  const cancelSelection = useCallback(() => {
    selectionRequest.current?.abort();
    selectionRequest.current = null;
    setSelecting(false);
    setResolutionError(null);
  }, []);

  useLayoutEffect(() => {
    cancelSelection();
    if (value !== undefined) setQuery(value);
    return () => selectionRequest.current?.abort();
  }, [cancelSelection, value, disabled]);

  function dismiss() {
    cancelSelection();
    setOpen(false);
    setActiveIndex(0);
  }

  useEffect(() => {
    function outside(event: PointerEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        cancelSelection();
        setOpen(false);
      }
    }
    document.addEventListener('pointerdown', outside);
    return () => document.removeEventListener('pointerdown', outside);
  }, [cancelSelection]);

  async function choose(source: SelectableInstrument) {
    if (disabled || !open || selectionRequest.current) return;
    const request = new AbortController();
    selectionRequest.current = request;
    setSelecting(true);
    setResolutionError(null);
    try {
      const instrument = await instrumentService.get(source.instrument_id);
      if (request.signal.aborted) return;
      onSelect(instrument);
      setOpen(false);
      setActiveIndex(0);
      setQuery(clearOnSelect ? '' : instrument.symbol);
    } catch (error) {
      if (!request.signal.aborted) {
        setResolutionError(error instanceof Error ? error.message : 'Could not resolve the selected instrument');
      }
    } finally {
      if (selectionRequest.current === request) {
        selectionRequest.current = null;
        setSelecting(false);
      }
    }
  }

  const dropdownItems = useMemo<SelectableInstrument[]>(() => {
    const result = search.result;
    if (!result) return [];
    if (result.status === 'resolved' && result.instrument) {
      const match = result.instrument;
      return [match, ...result.candidates.filter(candidate => candidate.instrument_id !== match.instrument_id)];
    }
    return result.status === 'ambiguous' ? result.candidates : [];
  }, [search.result]);

  useEffect(() => {
    if (activeIndex >= dropdownItems.length) {
      setActiveIndex(Math.max(dropdownItems.length - 1, 0));
    }
  }, [activeIndex, dropdownItems.length]);

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      if (open && query.trim()) {
        event.preventDefault();
        event.stopPropagation();
      }
      dismiss();
      return;
    }
    if (event.key === 'Enter' && open) event.preventDefault();
    if (!open && (event.key === 'ArrowDown' || event.key === 'ArrowUp')) {
      event.preventDefault();
      setOpen(true);
      return;
    }
    if (!dropdownItems.length) {
      return;
    }
    if (event.key === 'ArrowDown') {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((index) => (index + 1) % dropdownItems.length);
      return;
    }
    if (event.key === 'ArrowUp') {
      event.preventDefault();
      setOpen(true);
      setActiveIndex((index) => (index - 1 + dropdownItems.length) % dropdownItems.length);
      return;
    }
    if (event.key !== 'Enter' || !open) {
      return;
    }
    event.preventDefault();
    const selected = dropdownItems[activeIndex] ?? dropdownItems[0];
    if (selected) {
      void choose(selected);
    }
  }

  const showDropdown = open && !disabled && query.trim().length > 0;
  const rows = dropdownItems;

  return (
    <div ref={containerRef} onBlur={(event) => {
      if (!event.currentTarget.contains(event.relatedTarget)) dismiss();
    }} className={cn('relative min-w-0', className)}>
      <span className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-terminal-muted">
        <Icon name="search" size={13} />
      </span>
      <input
        value={query}
        onChange={(event) => {
          cancelSelection();
          onQueryEdit?.();
          setQuery(event.target.value);
          setActiveIndex(0);
          setOpen(true);
        }}
        onClick={() => setOpen(true)}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        aria-label="Instrument Search"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={showDropdown}
        aria-controls={showDropdown ? listboxId : undefined}
        aria-activedescendant={
          showDropdown && rows[activeIndex]
            ? `${listboxId}-option-${rows[activeIndex].instrument_id}`
            : undefined
        }
        autoComplete="off"
        autoFocus={autoFocus}
        disabled={disabled}
        className={cn(
          'h-7 w-full rounded-md border border-terminal-border bg-terminal-panelAlt pl-7 pr-2 text-xs text-terminal-text',
          'placeholder:text-terminal-muted/70 focus:border-terminal-accent focus:outline-none',
          inputClassName,
        )}
      />

      {showDropdown ? (
        <div
          id={listboxId}
          role="listbox"
          aria-label="Instrument search results"
          className="absolute left-0 right-0 top-[calc(100%+3px)] z-50 max-h-72 overflow-y-auto rounded border border-terminal-border bg-terminal-panel"
        >
          {resolutionError ? <p role="alert" className="px-2 py-1.5 text-2xs text-terminal-red">{resolutionError}</p> : null}
          {search.loading ? (
            <p className="px-2 py-1.5 text-2xs text-terminal-muted">Recognizing Instrument…</p>
          ) : search.error ? (
            <p role="alert" className="px-2 py-1.5 text-2xs text-terminal-red">{search.error}</p>
          ) : search.result?.status === 'ambiguous' ? (
            <>
              <p className="border-b border-terminal-borderSoft px-2 py-1 text-2xs text-terminal-amber">
                {search.result?.message ?? 'Multiple Supported Instruments Found'}
              </p>
              {rows.map((candidate, index) => (
                <CandidateRow
                  key={candidate.instrument_id}
                  id={`${listboxId}-option-${candidate.instrument_id}`}
                  candidate={candidate}
                  disabled={selecting}
                  active={index === activeIndex}
                  onChoose={() => void choose(candidate)}
                />
              ))}
            </>
          ) : search.result?.status === 'unsupported' ? (
            <p className="px-2 py-1.5 text-2xs text-terminal-amber">
              {search.result?.message ?? 'Instrument Recognized — Market Data Unavailable'}
            </p>
          ) : search.result?.status === 'not_found' ? (
            <p className="px-2 py-1.5 text-2xs text-terminal-muted">
              {search.result?.message ?? 'No Supported Instrument Found'}
            </p>
          ) : rows.length > 0 ? (
            rows.map((candidate, index) => (
              <CandidateRow
                key={candidate.instrument_id}
                id={`${listboxId}-option-${candidate.instrument_id}`}
                candidate={candidate}
                disabled={selecting}
                primary={candidate.instrument_id === search.result?.instrument?.instrument_id}
                active={index === activeIndex}
                onChoose={() => void choose(candidate)}
              />
            ))
          ) : null}
        </div>
      ) : null}
    </div>
  );
}

function CandidateRow({
  candidate,
  primary = false,
  disabled,
  active = false,
  id,
  onChoose,
}: {
  candidate: InstrumentCandidate | Instrument;
  primary?: boolean;
  disabled: boolean;
  active?: boolean;
  id?: string;
  onChoose: () => void;
}) {
  const assetLabel =
    candidate.asset_label ??
    (candidate.asset_type === 'crypto' ? 'Cryptocurrency' : marketLabel(candidate));
  return (
    <button
      id={id}
      type="button"
      tabIndex={-1}
      role="option"
      aria-selected={active}
      disabled={disabled}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onChoose}
      className={cn(
        'flex w-full items-center justify-between gap-2 px-2 py-1 text-left hover:bg-terminal-hover disabled:opacity-60',
        (primary || active) && 'bg-terminal-surface-2',
      )}
    >
      <span className="min-w-0">
        <span className="flex items-baseline gap-1.5">
          <span className="text-xs font-semibold text-terminal-text">{candidate.symbol}</span>
          <span className="truncate text-2xs text-terminal-muted">{candidate.name}</span>
        </span>
        <span className="block truncate text-2xs text-terminal-muted">
          {assetLabel} · {candidate.exchange} · {candidate.currency}
        </span>
      </span>
      {primary ? <span className="text-2xs text-terminal-accent">Best Match</span> : null}
    </button>
  );
}
