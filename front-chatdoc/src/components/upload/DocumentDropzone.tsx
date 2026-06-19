import { useCallback } from 'react'
import { useDropzone } from 'react-dropzone'
import { CloudUpload, Upload } from 'lucide-react'
import { cn } from '@/lib/utils'
import { FileUploadCard, type FileUploadState } from './FileUploadCard'

const ACCEPTED_TYPES = {
  'application/pdf': ['.pdf'],
  'application/vnd.openxmlformats-officedocument.wordprocessingml.document': ['.docx'],
  'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet': ['.xlsx'],
  'text/plain': ['.txt'],
}

interface DocumentDropzoneProps {
  uploads: FileUploadState[]
  onFilesAdded: (files: File[]) => void
  onRemoveFile: (id: string) => void
  disabled?: boolean
}

export function DocumentDropzone({ uploads, onFilesAdded, onRemoveFile, disabled }: DocumentDropzoneProps) {
  const onDrop = useCallback(
    (accepted: File[]) => { if (accepted.length) onFilesAdded(accepted) },
    [onFilesAdded],
  )

  const { getRootProps, getInputProps, isDragActive, fileRejections } = useDropzone({
    onDrop,
    accept: ACCEPTED_TYPES,
    multiple: true,
    disabled,
  })

  return (
    <div className="space-y-3">
      {/* Drop zone */}
      <div
        {...getRootProps()}
        className={cn(
          'border-2 border-dashed rounded-xl p-8 text-center cursor-pointer',
          'transition-all duration-200 outline-none',
          'focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-1',
          isDragActive
            ? 'border-primary bg-primary/5 scale-[1.01] shadow-sm'
            : disabled
            ? 'border-muted opacity-50 cursor-not-allowed pointer-events-none'
            : 'border-border hover:border-primary/50 hover:bg-muted/30',
        )}
      >
        <input {...getInputProps()} />

        <div className="flex flex-col items-center gap-3 pointer-events-none">
          <div className={cn(
            'w-14 h-14 rounded-full flex items-center justify-center transition-colors',
            isDragActive ? 'bg-primary/20' : 'bg-muted',
          )}>
            {isDragActive
              ? <CloudUpload className="w-7 h-7 text-primary" />
              : <Upload className="w-7 h-7 text-muted-foreground" />
            }
          </div>

          {isDragActive ? (
            <p className="text-sm font-semibold text-primary">Drop files to upload</p>
          ) : (
            <>
              <div>
                <p className="text-sm font-semibold">Drag & drop files here, or click to select</p>
                <p className="text-xs text-muted-foreground mt-1">
                  Supports <span className="font-medium">PDF, DOCX, XLSX, TXT</span> — up to 50 MB each
                </p>
              </div>
              <p className="text-xs text-muted-foreground/60">Multiple files can be selected at once</p>
            </>
          )}
        </div>
      </div>

      {/* Rejected files notice */}
      {fileRejections.length > 0 && (
        <p className="text-xs text-destructive px-1">
          {fileRejections.length} file{fileRejections.length > 1 ? 's' : ''} rejected —
          only PDF, DOCX, XLSX, and TXT formats are supported.
        </p>
      )}

      {/* File upload cards */}
      {uploads.length > 0 && (
        <div className="space-y-2 max-h-72 overflow-y-auto pr-0.5">
          {uploads.map(item => (
            <FileUploadCard key={item.id} item={item} onRemove={onRemoveFile} />
          ))}
        </div>
      )}
    </div>
  )
}
