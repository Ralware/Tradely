import type {
  InputHTMLAttributes,
  ReactNode,
  SelectHTMLAttributes,
  TextareaHTMLAttributes,
} from 'react';
import { useId } from 'react';
import { cn } from '../../utils/format';

const controlClasses =
  'w-full rounded-sm border border-terminal-border bg-terminal-panel px-2 py-1.5 text-xs text-terminal-text ' +
  'placeholder:text-terminal-muted/70 transition-colors hover:border-[#30353f] ' +
  'focus:outline-none focus:ring-1 focus:ring-terminal-accent focus:border-terminal-accent disabled:opacity-60';

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
        className="mb-1 block text-2xs font-medium text-terminal-muted"
      >
        {label}
      </label>
      {children}
      {error ? (
        <p className="mt-0.5 text-2xs text-terminal-red">{error}</p>
      ) : hint ? (
        <p className="mt-0.5 text-2xs text-terminal-muted">{hint}</p>
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
    <select id={selectId} className={cn(controlClasses, 'appearance-none pr-7', className)} {...rest}>
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
    <textarea id={textareaId} className={cn(controlClasses, 'min-h-[70px]', className)} {...rest} />
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
