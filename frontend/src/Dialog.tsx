import {useEffect, useRef} from 'react'
import type {ReactNode} from 'react'

/** Native modal provides focus trapping, Escape and an inert background. */
export default function Dialog({children, className, titleId, onClose}: {
  children: ReactNode; className?: string; titleId: string; onClose: () => void
}) {
  const ref = useRef<HTMLDialogElement>(null)
  const close = useRef(onClose)
  close.current = onClose
  useEffect(() => {
    const previous = document.activeElement as HTMLElement | null
    const dialog = ref.current
    dialog?.showModal()
    return () => {dialog?.close(); previous?.focus()}
  }, [])
  return <dialog ref={ref} className={className} aria-labelledby={titleId}
    onCancel={event => {event.preventDefault(); close.current()}}
    onClick={event => {if (event.target === event.currentTarget) close.current()}}>
    {children}
  </dialog>
}
