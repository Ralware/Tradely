import { useEffect, useId, useMemo, useRef, useState } from 'react';
import type { KeyboardEvent } from 'react';
import { useInstrumentSearch } from '../../hooks/useInstrumentSearch';
import { instrumentService } from '../../services/instrumentService';
import type { Instrument, InstrumentCandidate } from '../../types/api';
import { cn } from '../../utils/format';
import { Icon } from '../common/Icon';

type SelectableInstrument = Instrument | InstrumentCandidate;

function normalizeInstrument(source: SelectableInstrument): Instrument {
  return {
    instrument_id: source.instrument_id,
    symbol: source.symbol,
    name: source.name,
    market: source.market,
    exchange: source.exchange,
    currency: source.currency,
    asset_type: source.asset_type,
    provider: source.provider,
    provider_symbol: source.provider_symbol,
    display_name: source.display_name ?? source.name ?? null,
    base_currency: source.base_currency ?? null,
    quote_currency: source.quote_currency ?? null,
    trading_pair: source.trading_pair ?? null,
    status: source.status,
    asset_label: source.asset_label,
  };
}

function marketLabel(instrument: Pick<Instrument, 'market' | 'asset_type'>): string {
  if (instrument.asset_type === 'crypto') return 'Crypto';
  return instrument.market === 'india' ? 'India' : 'Global';
}

export function InstrumentSearch({
  value,
  placeholder = 'Search Ticker Or Name',
  onSelect,
  className,
  inputClassName,
  autoFocus = false,
  disabled = false,
  clearOnSelect = false,
}: {
  value?: string;
  placeholder?: string;
  onSelect: (instrument: Instrument) => void;
  className?: string;
  inputClassName?: string;
  autoFocus?: boolean;
  disabled?: boolean;
  clearOnSelect?: boolean;
}) {
  const search = useInstrumentSearch(value ?? '');
  const listboxId = useId();
  const [open, setOpen] = useState(false);
  const [selecting, setSelecting] = useState(false);
  const [activeIndex, setActiveIndex] = useState(0);
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (value !== undefined && value !== search.query) {
      search.setQuery(value);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [value]);

  useEffect(() => {
    function onDocumentPointer(event: MouseEvent) {
      if (!containerRef.current?.contains(event.target as Node)) {
        setOpen(false);
      }
    }
    document.addEventListener('mousedown', onDocumentPointer);
    return () => document.removeEventListener('mousedown', onDocumentPointer);
  }, []);

  async function choose(source: SelectableInstrument) {
    setSelecting(true);
    try {
      const instrument = normalizeInstrument(source);
      let resolvedInstrument: Instrument = instrument;
      try {
        resolvedInstrument = await instrumentService.get(instrument.instrument_id);
      } catch {
        resolvedInstrument = instrument;
      }
      onSelect(resolvedInstrument);
      setOpen(false);
      setActiveIndex(0);
      search.setQuery(clearOnSelect ? '' : resolvedInstrument.symbol);
      if (clearOnSelect) {
        search.reset();
      }
    } finally {
      setSelecting(false);
    }
  }

  const dropdownItems = useMemo<SelectableInstrument[]>(() => {
    if (search.status === 'resolved' && search.instrument) {
      if (search.candidates.length === 0) {
        return [search.instrument];
      }
      return [search.instrument, ...search.candidates.filter((candidate) => candidate.instrument_id !== search.instrument?.instrument_id)];
    }
    return search.candidates;
  }, [search.candidates, search.instrument, search.status]);

  useEffect(() => {
    if (activeIndex >= dropdownItems.length) {
      setActiveIndex(Math.max(dropdownItems.length - 1, 0));
    }
  }, [activeIndex, dropdownItems.length]);

  function onKeyDown(event: KeyboardEvent<HTMLInputElement>) {
    if (event.key === 'Escape') {
      setOpen(false);
      setActiveIndex(0);
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
    if (event.key !== 'Enter') {
      return;
    }
    event.preventDefault();
    const selected = dropdownItems[activeIndex] ?? dropdownItems[0];
    if (selected) {
      void choose(selected);
    }
  }

  const showDropdown = open && search.query.trim().length > 0;
  const rows = dropdownItems;
  const fallbackInstrument =
    search.status === 'resolved' && search.instrument && rows.length === 0
      ? search.instrument
      : null;

  return (
    <div ref={containerRef} className={cn('relative min-w-0', className)}>
      <span className="pointer-events-none absolute left-2 top-1/2 -translate-y-1/2 text-terminal-muted">
        <Icon name="search" size={13} />
      </span>
      <input
        value={search.query}
        onChange={(event) => {
          search.setQuery(event.target.value);
          setOpen(true);
        }}
        onFocus={() => setOpen(true)}
        onKeyDown={onKeyDown}
        placeholder={placeholder}
        aria-label="Instrument Search"
        role="combobox"
        aria-autocomplete="list"
        aria-expanded={showDropdown}
        aria-controls={listboxId}
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
          className="absolute left-0 right-0 top-[calc(100%+3px)] z-50 max-h-72 overflow-y-auto rounded-md border border-terminal-border bg-terminal-panel shadow-xl"
        >
          {search.loading ? (
            <p className="px-2 py-1.5 text-2xs text-terminal-muted">Recognizing Instrument…</p>
          ) : search.error ? (
            <p className="px-2 py-1.5 text-2xs text-terminal-red">{search.error}</p>
          ) : search.status === 'ambiguous' ? (
            <>
              <p className="border-b border-terminal-borderSoft px-2 py-1 text-2xs text-terminal-amber">
                {search.message ?? 'Multiple Supported Instruments Found'}
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
          ) : search.status === 'unsupported' ? (
            <p className="px-2 py-1.5 text-2xs text-terminal-amber">
              {search.message ?? 'Instrument Recognized — Market Data Unavailable'}
            </p>
          ) : search.status === 'not_found' ? (
            <p className="px-2 py-1.5 text-2xs text-terminal-muted">
              {search.message ?? 'No Supported Instrument Found'}
            </p>
          ) : fallbackInstrument ? (
            <CandidateRow
              id={`${listboxId}-option-${fallbackInstrument.instrument_id}`}
              candidate={fallbackInstrument}
              disabled={selecting}
              primary
              active
              onChoose={() => void choose(fallbackInstrument)}
            />
          ) : rows.length > 0 ? (
            rows.map((candidate, index) => (
              <CandidateRow
                key={candidate.instrument_id}
                id={`${listboxId}-option-${candidate.instrument_id}`}
                candidate={candidate}
                disabled={selecting}
                primary={candidate.instrument_id === search.instrument?.instrument_id}
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
      role="option"
      aria-selected={active}
      disabled={disabled}
      onMouseDown={(event) => event.preventDefault()}
      onClick={onChoose}
      className={cn(
        'flex w-full items-center justify-between gap-2 px-2 py-1 text-left hover:bg-white/[0.05] disabled:opacity-60',
        (primary || active) && 'bg-white/[0.04]',
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
