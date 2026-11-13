import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react';
import { useId } from 'react';
import { cn } from '../../utils/format';

const controlClasses =
  'w-full rounded-lg border border-terminal-border bg-terminal-panelAlt px-3 py-2 text-sm text-terminal-text ' +
  'placeholder:text-terminal-muted/70 transition-colors hover:border-[#2c3a4d] ' +
  'focus:border-[#40598f] focus:outline-none focus:ring-1 focus:ring-[#40598f] disabled:opacity-60';

interface FieldProps {
  label: string;
  htmlFor?: string;
  hint?: ReactNode;
  error?: string | null;
  children: ReactNode;
  className?: string;
}

export function Field({ label, htmlFor, hint, error, children, className }: FieldProps) {
  return (
    <div className={cn('min-w-0', className)}>
      <label
        htmlFor={htmlFor}
        className="mb-1.5 block text-[11px] font-medium uppercase tracking-[0.08em] text-terminal-muted"
      >
        {label}
      </label>
      {children}
      {error ? (
        <p className="mt-1 text-xs text-terminal-red">{error}</p>
      ) : hint ? (
        <p className="mt-1 text-xs text-terminal-muted">{hint}</p>
      ) : null}
    </div>
  );
}

interface InputProps extends InputHTMLAttributes<HTMLInputElement> {
  label?: string;
  hint?: ReactNode;
  error?: string | null;
  wrapperClassName?: string;
}

export function Input({ label, hint, error, wrapperClassName, id, className, ...rest }: InputProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  const control = <input id={inputId} className={cn(controlClasses, className)} {...rest} />;
  if (!label) {
    return control;
  }
  return (
    <Field label={label} htmlFor={inputId} hint={hint} error={error} className={wrapperClassName}>
      {control}
    </Field>
  );
}

interface SelectProps extends SelectHTMLAttributes<HTMLSelectElement> {
  label?: string;
  hint?: ReactNode;
  error?: string | null;
  wrapperClassName?: string;
  options: Array<{ value: string; label: string }>;
}

export function Select({
  label,
  hint,
  error,
  wrapperClassName,
  options,
  id,
  className,
  ...rest
}: SelectProps) {
  const generatedId = useId();
  const selectId = id ?? generatedId;
  const control = (
    <select id={selectId} className={cn(controlClasses, 'appearance-none pr-8', className)} {...rest}>
      {options.map((option) => (
        <option key={option.value} value={option.value}>
          {option.label}
        </option>
      ))}
    </select>
  );
  if (!label) {
    return control;
  }
  return (
    <Field label={label} htmlFor={selectId} hint={hint} error={error} className={wrapperClassName}>
      {control}
    </Field>
  );
}

interface TextareaProps extends TextareaHTMLAttributes<HTMLTextAreaElement> {
  label?: string;
  hint?: ReactNode;
  error?: string | null;
  wrapperClassName?: string;
}

export function Textarea({
  label,
  hint,
  error,
  wrapperClassName,
  id,
  className,
  ...rest
}: TextareaProps) {
  const generatedId = useId();
  const textareaId = id ?? generatedId;
  const control = (
    <textarea id={textareaId} className={cn(controlClasses, 'min-h-[80px]', className)} {...rest} />
  );
  if (!label) {
    return control;
  }
  return (
    <Field
      label={label}
      htmlFor={textareaId}
      hint={hint}
      error={error}
      className={wrapperClassName}
    >
      {control}
    </Field>
  );
}
