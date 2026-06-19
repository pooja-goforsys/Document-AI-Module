import { useState, useCallback } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import {
  FolderOpen, FolderPlus, Pencil, Trash2, Upload, Search,
  FileText, File, Grid3X3, List, RefreshCw, Check, X, ChevronRight, ExternalLink,
  BookOpen, Loader2, Clock, AlertCircle,
} from 'lucide-react'
import type { Document as DocType } from '@/types'
import { toast } from 'sonner'
import { Button } from '@/components/ui/button'
import { Input } from '@/components/ui/input'
import { Badge } from '@/components/ui/badge'
import { Card, CardContent } from '@/components/ui/card'
import {
  Dialog, DialogContent, DialogHeader, DialogTitle,
  DialogFooter, DialogDescription,
} from '@/components/ui/dialog'
import {
  uploadDocument, getDocuments, deleteDocument, reindexDocument,
  getFolders, createFolder, renameFolder, deleteFolder,
  getDocumentFileUrl, updateDocument, replaceDocumentFile,
} from '@/services/api'
import { formatFileSize, formatDate, cn } from '@/lib/utils'
import { DocumentsSkeleton } from '@/components/skeletons/DocumentsSkeleton'
import { DocumentDropzone } from '@/components/upload/DocumentDropzone'
import { UploadProgress } from '@/components/upload/UploadProgress'
import type { FileUploadState } from '@/components/upload/FileUploadCard'
import { SummarizeModal } from '@/components/chat/SummarizeModal'

// ── Status badge ──────────────────────────────────────────────────────────────

function StatusBadge({ doc }: { doc: DocType }) {
  if (doc.status === 'indexing') {
    return (
      <Badge variant="secondary" className="gap-1 text-blue-600 border-blue-300/60 bg-blue-50 dark:bg-blue-950/30 dark:text-blue-400">
        <Loader2 className="w-3 h-3 animate-spin" />
        Indexing…
      </Badge>
    )
  }
  if (doc.status === 'failed') {
    return (
      <Badge variant="destructive" className="gap-1" title={doc.status}>
        <AlertCircle className="w-3 h-3" />
        Failed
      </Badge>
    )
  }
  if (doc.indexed) {
    return <Badge variant="success">Indexed</Badge>
  }
  return (
    <Badge variant="warning" className="gap-1">
      <Clock className="w-3 h-3" />
      Pending
    </Badge>
  )
}

const FILE_COLOR: Record<string, string> = {
  pdf: 'text-red-500', docx: 'text-blue-500', xlsx: 'text-green-500', txt: 'text-gray-500',
}
const FILE_BG: Record<string, string> = {
  pdf:  'bg-red-50 dark:bg-red-900/20',
  docx: 'bg-blue-50 dark:bg-blue-900/20',
  xlsx: 'bg-green-50 dark:bg-green-900/20',
  txt:  'bg-gray-50 dark:bg-gray-900/20',
}

type FolderDialog = 'create' | 'rename' | 'delete' | null

export default function DocumentsPage() {
  const queryClient = useQueryClient()

  const [selectedFolder, setSelected] = useState<string | null>(null)
  const [search, setSearch]           = useState('')
  const [viewMode, setViewMode]       = useState<'grid' | 'list'>('list')
  const [uploadOpen, setUploadOpen]   = useState(false)
  const [folderDlg, setFolderDlg]     = useState<FolderDialog>(null)
  const [folderInput, setFolderInput] = useState('')

  // Multi-file upload state
  const [uploads, setUploads] = useState<FileUploadState[]>([])

  // Edit document state
  const [editDoc, setEditDoc]           = useState<DocType | null>(null)
  const [editName, setEditName]         = useState('')
  const [editFolderId, setEditFolderId] = useState<string>('')
  const [replaceFile, setReplaceFile]   = useState<File | null>(null)
  const [summarizeDoc, setSummarizeDoc] = useState<DocType | null>(null)

  function openEditDialog(doc: DocType) {
    setEditDoc(doc)
    setEditName(doc.name)
    setEditFolderId(doc.folder_id ?? '')
    setReplaceFile(null)
  }
  function closeEditDialog() { setEditDoc(null); setReplaceFile(null) }

  // ── Fetch data ───────────────────────────────────────────────────────────
  const { data: folders = [], isError: foldersError } = useQuery({
    queryKey: ['folders'],
    queryFn: () => getFolders(),
    retry: 1,
  })

  const { data: documents = [], isError: docsError, isLoading: docsLoading } = useQuery({
    queryKey: ['documents'],
    queryFn: () => getDocuments(),
    retry: 1,
    // Auto-poll every 3 s while any document is still being processed.
    // Stops automatically once all documents reach a terminal state.
    refetchInterval: (query) => {
      const docs = (query.state.data as DocType[] | undefined) ?? []
      return docs.some(d => d.status === 'pending' || d.status === 'indexing') ? 3000 : false
    },
    refetchIntervalInBackground: true,
  })

  const backendDown = foldersError || docsError

  const invalidateAll = () => {
    queryClient.invalidateQueries({ queryKey: ['documents'] })
    queryClient.invalidateQueries({ queryKey: ['folders'] })
    queryClient.invalidateQueries({ queryKey: ['stats'] })
  }

  // ── Multi-file upload ────────────────────────────────────────────────────
  function openUploadDialog() {
    // Clear completed/failed uploads when re-opening; keep active ones
    setUploads(prev => prev.filter(u => u.status === 'uploading' || u.status === 'queued'))
    setUploadOpen(true)
  }

  const handleFilesAdded = useCallback((files: File[]) => {
    // Deduplicate against currently active uploads
    const activeNames = new Set(
      uploads
        .filter(u => u.status === 'uploading' || u.status === 'queued')
        .map(u => u.file.name),
    )

    const newFiles = files.filter(f => !activeNames.has(f.name))
    const dupeCount = files.length - newFiles.length

    if (dupeCount > 0) {
      toast.warning(`${dupeCount} file${dupeCount > 1 ? 's are' : ' is'} already uploading — skipped.`)
    }
    if (newFiles.length === 0) return

    const newItems: FileUploadState[] = newFiles.map(f => ({
      file: f,
      id: `${Date.now()}-${Math.random().toString(36).slice(2, 9)}`,
      status: 'uploading' as const,
      progress: 0,
    }))

    setUploads(prev => [...prev, ...newItems])

    // Capture folder at time of drop
    const targetFolder = selectedFolder

    newItems.forEach(item => {
      uploadDocument(item.file, targetFolder, (pct) => {
        setUploads(prev => prev.map(u => u.id === item.id ? { ...u, progress: pct } : u))
      })
        .then((doc) => {
          setUploads(prev => prev.map(u =>
            u.id === item.id ? { ...u, status: 'completed', progress: 100 } : u,
          ))
          invalidateAll()
          toast.success(`"${doc.name}" uploaded — indexing started.`)
        })
        .catch((err: unknown) => {
          const msg =
            (err as { response?: { data?: { detail?: string } } })?.response?.data?.detail ??
            'Upload failed. Please try again.'
          setUploads(prev => prev.map(u =>
            u.id === item.id ? { ...u, status: 'failed', error: msg } : u,
          ))
          toast.error(msg)
        })
    })
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [uploads, selectedFolder])

  function removeUpload(id: string) {
    setUploads(prev => prev.filter(u => u.id !== id))
  }

  const hasActiveUploads = uploads.some(u => u.status === 'uploading' || u.status === 'queued')

  // ── Delete document ──────────────────────────────────────────────────────
  const deleteDocMut = useMutation({
    mutationFn: (docId: string) => deleteDocument(docId),
    onSuccess: () => { invalidateAll(); toast.success('Document deleted.') },
    onError:   () => toast.error('Failed to delete document.'),
  })

  // ── Reindex document ─────────────────────────────────────────────────────
  const reindexMut = useMutation({
    mutationFn: (docId: string) => reindexDocument(docId),
    onSuccess: () => { invalidateAll(); toast.success('Re-indexing started.') },
    onError:   () => toast.error('Failed to start re-indexing.'),
  })

  // ── Edit / replace ───────────────────────────────────────────────────────
  const updateDocMut = useMutation({
    mutationFn: ({ id, body }: { id: string; body: { name?: string; folder_id?: string | null } }) =>
      updateDocument(id, body),
    onSuccess: () => { invalidateAll(); toast.success('Document updated.') },
    onError:   () => toast.error('Failed to update document.'),
  })

  const replaceFileMut = useMutation({
    mutationFn: ({ id, file }: { id: string; file: File }) => replaceDocumentFile(id, file),
    onSuccess: () => { invalidateAll(); toast.success('File replaced — re-indexing in background.') },
    onError:   () => toast.error('Failed to replace file.'),
  })

  async function saveEdit() {
    if (!editDoc) return
    const nameChanged   = editName.trim() !== editDoc.name
    const folderChanged = (editFolderId || null) !== (editDoc.folder_id ?? null)

    if (nameChanged || folderChanged) {
      const body: { name?: string; folder_id?: string | null } = {}
      if (nameChanged)   body.name      = editName.trim()
      if (folderChanged) body.folder_id = editFolderId || null
      updateDocMut.mutate({ id: editDoc.id, body })
    }
    if (replaceFile) replaceFileMut.mutate({ id: editDoc.id, file: replaceFile })
    if (!nameChanged && !folderChanged && !replaceFile) toast.info('No changes to save.')
    closeEditDialog()
  }

  // ── Folder mutations ─────────────────────────────────────────────────────
  const createFolderMut = useMutation({
    mutationFn: (name: string) => createFolder(name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['folders'] })
      queryClient.invalidateQueries({ queryKey: ['stats'] })
      setFolderInput(''); setFolderDlg(null)
      toast.success('Folder created.')
    },
    onError: () => toast.error('Failed to create folder.'),
  })

  const renameFolderMut = useMutation({
    mutationFn: ({ id, name }: { id: string; name: string }) => renameFolder(id, name),
    onSuccess: () => {
      queryClient.invalidateQueries({ queryKey: ['folders'] })
      queryClient.invalidateQueries({ queryKey: ['documents'] })
      setFolderInput(''); setFolderDlg(null)
      toast.success('Folder renamed.')
    },
    onError: () => toast.error('Failed to rename folder.'),
  })

  const deleteFolderMut = useMutation({
    mutationFn: (id: string) => deleteFolder(id),
    onSuccess: () => {
      invalidateAll(); setSelected(null); setFolderDlg(null)
      toast.success('Folder deleted.')
    },
    onError: () => toast.error('Failed to delete folder.'),
  })

  // ── Filtered docs ────────────────────────────────────────────────────────
  const filteredDocs = documents.filter(d => {
    const inFolder    = selectedFolder ? d.folder_id === selectedFolder : true
    const matchSearch = d.name.toLowerCase().includes(search.toLowerCase())
    return inFolder && matchSearch
  })

  const activeFolder = folders.find(f => f.id === selectedFolder)

  if (docsLoading) return <DocumentsSkeleton />

  return (
    <>
    <div className="flex h-full">
      {/* Folder sidebar */}
      <aside className="w-56 shrink-0 border-r bg-background flex flex-col">
        <div className="flex items-center justify-between px-4 py-3 border-b">
          <span className="text-sm font-semibold">Folders</span>
          <Button variant="ghost" size="icon" className="h-7 w-7"
            onClick={() => { setFolderInput(''); setFolderDlg('create') }}>
            <FolderPlus className="w-4 h-4" />
          </Button>
        </div>

        <nav className="flex-1 overflow-y-auto p-2 space-y-0.5">
          <button
            onClick={() => setSelected(null)}
            className={cn(
              'w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors text-left',
              selectedFolder === null ? 'bg-primary text-white' : 'hover:bg-muted text-foreground',
            )}
          >
            <FolderOpen className="w-4 h-4 shrink-0" />
            <span className="flex-1 truncate">All Documents</span>
            <span className={cn('text-xs shrink-0', selectedFolder === null ? 'text-white/70' : 'text-muted-foreground')}>
              {documents.length}
            </span>
          </button>

          {folders.map(folder => (
            <button
              key={folder.id}
              onClick={() => setSelected(folder.id)}
              className={cn(
                'w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm transition-colors text-left group',
                selectedFolder === folder.id ? 'bg-primary text-white' : 'hover:bg-muted text-foreground',
              )}
            >
              <FolderOpen className="w-4 h-4 shrink-0" />
              <span className="flex-1 truncate">{folder.name}</span>
              <span className={cn('text-xs shrink-0', selectedFolder === folder.id ? 'text-white/70' : 'text-muted-foreground')}>
                {documents.filter(d => d.folder_id === folder.id).length}
              </span>
            </button>
          ))}
        </nav>

        {selectedFolder && (
          <div className="p-2 border-t space-y-1">
            <Button variant="ghost" size="sm" className="w-full justify-start text-xs"
              onClick={() => { setFolderInput(activeFolder?.name ?? ''); setFolderDlg('rename') }}>
              <Pencil className="w-3.5 h-3.5 mr-2" /> Rename Folder
            </Button>
            <Button variant="ghost" size="sm" className="w-full justify-start text-xs text-destructive hover:text-destructive"
              onClick={() => setFolderDlg('delete')}>
              <Trash2 className="w-3.5 h-3.5 mr-2" /> Delete Folder
            </Button>
          </div>
        )}
      </aside>

      {/* Main content */}
      <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
        {/* Toolbar */}
        <div className="flex items-center gap-3 px-6 py-3 border-b bg-background">
          <div className="flex items-center gap-1 text-sm text-muted-foreground">
            <span>Documents</span>
            {activeFolder && (
              <>
                <ChevronRight className="w-3.5 h-3.5" />
                <span className="text-foreground font-medium">{activeFolder.name}</span>
              </>
            )}
          </div>
          <div className="flex-1" />
          <div className="relative w-52">
            <Search className="absolute left-2.5 top-1/2 -translate-y-1/2 w-3.5 h-3.5 text-muted-foreground" />
            <Input className="pl-8 h-8 text-sm" placeholder="Search…"
              value={search} onChange={e => setSearch(e.target.value)} />
          </div>
          <div className="flex border rounded-md overflow-hidden">
            {(['list', 'grid'] as const).map(mode => (
              <button key={mode} onClick={() => setViewMode(mode)}
                className={cn('p-1.5 transition-colors', viewMode === mode ? 'bg-primary text-white' : 'hover:bg-muted')}>
                {mode === 'list' ? <List className="w-3.5 h-3.5" /> : <Grid3X3 className="w-3.5 h-3.5" />}
              </button>
            ))}
          </div>
          <Button size="sm" onClick={openUploadDialog}>
            <Upload className="w-3.5 h-3.5 mr-1.5" /> Upload
          </Button>
        </div>

        {/* Documents list/grid */}
        <div className="flex-1 overflow-auto p-6">
          {backendDown ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
              <div className="w-12 h-12 rounded-full bg-destructive/10 flex items-center justify-center">
                <RefreshCw className="w-6 h-6 text-destructive" />
              </div>
              <p className="font-medium text-sm">Cannot reach the backend</p>
              <p className="text-muted-foreground text-xs max-w-xs">
                Make sure the server is running:<br />
                <code className="bg-muted px-1 py-0.5 rounded text-xs">cd backend</code><br />
                <code className="bg-muted px-1 py-0.5 rounded text-xs">uvicorn app.main:app --reload</code>
              </p>
              <Button size="sm" variant="outline" onClick={() => queryClient.invalidateQueries()}>
                <RefreshCw className="w-3.5 h-3.5 mr-1.5" /> Retry
              </Button>
            </div>
          ) : filteredDocs.length === 0 ? (
            <div className="flex flex-col items-center justify-center h-full gap-3 text-center">
              <FileText className="w-12 h-12 text-muted-foreground/30" />
              <p className="text-muted-foreground text-sm">
                {selectedFolder ? 'No documents in this folder.' : 'No documents found.'}
              </p>
              <Button size="sm" onClick={openUploadDialog}>
                <Upload className="w-4 h-4 mr-1.5" /> Upload a document
              </Button>
            </div>
          ) : viewMode === 'list' ? (
            <div className="border rounded-lg overflow-hidden bg-background">
              <table className="w-full text-sm">
                <thead className="bg-muted/50">
                  <tr className="border-b">
                    {['Name', 'Folder', 'Size', 'Uploaded', 'Status', ''].map(h => (
                      <th key={h} className="text-left px-4 py-2.5 font-medium text-muted-foreground text-xs">{h}</th>
                    ))}
                  </tr>
                </thead>
                <tbody className="divide-y">
                  {filteredDocs.map(doc => (
                    <tr key={doc.id} className="hover:bg-muted/30 transition-colors group/row">
                      <td className="px-4 py-3">
                        <button
                          className="flex items-center gap-2.5 text-left w-full group/name"
                          onClick={() => window.open(getDocumentFileUrl(doc.id), '_blank', 'noopener,noreferrer')}
                          title={`Open ${doc.name}`}
                        >
                          <div className={cn('w-7 h-7 rounded flex items-center justify-center shrink-0 transition-transform group-hover/name:scale-110', FILE_BG[doc.type] ?? FILE_BG.pdf)}>
                            <FileText className={cn('w-3.5 h-3.5', FILE_COLOR[doc.type] ?? FILE_COLOR.pdf)} />
                          </div>
                          <span className="font-medium truncate max-w-[200px] group-hover/name:text-primary transition-colors">
                            {doc.name}
                          </span>
                          <ExternalLink className="w-3 h-3 text-muted-foreground opacity-0 group-hover/name:opacity-100 transition-opacity shrink-0" />
                        </button>
                      </td>
                      <td className="px-4 py-3 text-muted-foreground text-xs">{doc.folder_name ?? '—'}</td>
                      <td className="px-4 py-3 text-muted-foreground text-xs">{doc.size ? formatFileSize(doc.size) : '—'}</td>
                      <td className="px-4 py-3 text-muted-foreground text-xs">{formatDate(doc.uploaded_at)}</td>
                      <td className="px-4 py-3">
                        <StatusBadge doc={doc} />
                      </td>
                      <td className="px-4 py-3">
                        <div className="flex items-center gap-1 justify-end">
                          <Button variant="ghost" size="icon" className="h-7 w-7" title="AI Summary"
                            onClick={() => setSummarizeDoc(doc)} disabled={!doc.indexed}>
                            <BookOpen className="w-3.5 h-3.5" />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-7 w-7" title="Edit document"
                            onClick={() => openEditDialog(doc)}>
                            <Pencil className="w-3.5 h-3.5" />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-7 w-7" title="Re-index"
                            onClick={() => reindexMut.mutate(doc.id)} disabled={reindexMut.isPending}>
                            <RefreshCw className={cn('w-3.5 h-3.5', reindexMut.isPending && 'animate-spin')} />
                          </Button>
                          <Button variant="ghost" size="icon" className="h-7 w-7 text-destructive hover:text-destructive"
                            title="Delete" onClick={() => deleteDocMut.mutate(doc.id)}>
                            <Trash2 className="w-3.5 h-3.5" />
                          </Button>
                        </div>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          ) : (
            <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-4 xl:grid-cols-5 gap-4">
              {filteredDocs.map(doc => (
                <Card
                  key={doc.id}
                  className="group hover:shadow-md transition-all hover:border-primary/40 cursor-pointer"
                  onClick={() => window.open(getDocumentFileUrl(doc.id), '_blank', 'noopener,noreferrer')}
                  title={`Open ${doc.name}`}
                >
                  <CardContent className="p-4">
                    <div className={cn('w-full h-20 rounded-md flex items-center justify-center mb-3 transition-transform group-hover:scale-105', FILE_BG[doc.type] ?? FILE_BG.pdf)}>
                      <FileText className={cn('w-8 h-8', FILE_COLOR[doc.type] ?? FILE_COLOR.pdf)} />
                    </div>
                    <p className="text-xs font-medium truncate group-hover:text-primary transition-colors">{doc.name}</p>
                    <p className="text-xs text-muted-foreground mt-0.5">{doc.size ? formatFileSize(doc.size) : '—'}</p>
                    <p className="text-xs text-muted-foreground truncate mt-0.5">{doc.folder_name ?? '—'}</p>
                    <div className="flex items-center justify-between mt-2">
                      <StatusBadge doc={doc} />
                      <div className="flex items-center gap-1 opacity-0 group-hover:opacity-100 transition-opacity">
                        {doc.indexed && (
                          <button title="AI Summary" onClick={e => { e.stopPropagation(); setSummarizeDoc(doc) }}>
                            <BookOpen className="w-3.5 h-3.5 text-muted-foreground hover:text-primary" />
                          </button>
                        )}
                        <button title="Edit" onClick={e => { e.stopPropagation(); openEditDialog(doc) }}>
                          <Pencil className="w-3.5 h-3.5 text-muted-foreground hover:text-foreground" />
                        </button>
                        <button title="Delete" onClick={e => { e.stopPropagation(); deleteDocMut.mutate(doc.id) }}>
                          <Trash2 className="w-3.5 h-3.5 text-destructive" />
                        </button>
                      </div>
                    </div>
                  </CardContent>
                </Card>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* ── Edit document dialog ── */}
      <Dialog open={!!editDoc} onOpenChange={o => !o && closeEditDialog()}>
        <DialogContent className="max-w-md">
          <DialogHeader>
            <DialogTitle>Edit Document</DialogTitle>
            <DialogDescription>Update the document name, folder, or replace the file.</DialogDescription>
          </DialogHeader>

          <div className="space-y-4 py-1">
            <div className="space-y-1.5">
              <label className="text-sm font-medium">Document Name</label>
              <Input value={editName} onChange={e => setEditName(e.target.value)} placeholder="Document name" />
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Folder</label>
              <select
                value={editFolderId}
                onChange={e => setEditFolderId(e.target.value)}
                className="w-full h-9 rounded-md border border-input bg-background px-3 text-sm focus:outline-none focus:ring-2 focus:ring-ring"
              >
                <option value="">No Folder</option>
                {folders.map(f => <option key={f.id} value={f.id}>{f.name}</option>)}
              </select>
            </div>

            <div className="space-y-1.5">
              <label className="text-sm font-medium">Replace File</label>
              <div
                className={cn(
                  'border-2 border-dashed rounded-lg p-5 text-center cursor-pointer transition-colors',
                  'hover:border-primary/50 hover:bg-primary/5',
                  replaceFile ? 'border-primary/40 bg-primary/5' : 'border-border',
                )}
                onClick={() => document.getElementById('replace-file-input')?.click()}
              >
                <input
                  id="replace-file-input"
                  type="file"
                  className="hidden"
                  accept=".pdf,.docx,.xlsx,.txt"
                  onChange={e => setReplaceFile(e.target.files?.[0] ?? null)}
                />
                {replaceFile ? (
                  <div className="flex items-center gap-3 justify-between">
                    <div className="flex items-center gap-2 min-w-0">
                      <File className="w-4 h-4 text-primary shrink-0" />
                      <span className="text-sm font-medium truncate">{replaceFile.name}</span>
                    </div>
                    <button className="shrink-0" onClick={e => { e.stopPropagation(); setReplaceFile(null) }}>
                      <X className="w-4 h-4 text-muted-foreground hover:text-foreground" />
                    </button>
                  </div>
                ) : (
                  <>
                    <Upload className="w-5 h-5 mx-auto text-muted-foreground mb-1.5" />
                    <p className="text-xs text-muted-foreground">Click to select a new file <span className="text-muted-foreground/60">(PDF, DOCX, XLSX, TXT)</span></p>
                    <p className="text-xs text-muted-foreground/60 mt-0.5">Leave empty to keep the current file</p>
                  </>
                )}
              </div>
            </div>
          </div>

          <DialogFooter>
            <Button variant="outline" onClick={closeEditDialog}>Cancel</Button>
            <Button
              disabled={!editName.trim() || updateDocMut.isPending || replaceFileMut.isPending}
              onClick={saveEdit}
            >
              <Check className="w-4 h-4 mr-1.5" />
              {updateDocMut.isPending || replaceFileMut.isPending ? 'Saving…' : 'Save Changes'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Upload dialog ── */}
      <Dialog
        open={uploadOpen}
        onOpenChange={open => {
          if (!open && hasActiveUploads) {
            toast.info('Uploads are still in progress and will continue in the background.')
          }
          setUploadOpen(open)
        }}
      >
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle>Upload Documents</DialogTitle>
            <DialogDescription>
              {selectedFolder
                ? `Uploading to folder: "${activeFolder?.name}"`
                : 'Uploading to All Documents (no folder selected).'}
            </DialogDescription>
          </DialogHeader>

          <DocumentDropzone
            uploads={uploads}
            onFilesAdded={handleFilesAdded}
            onRemoveFile={removeUpload}
            disabled={false}
          />

          {uploads.length > 0 && (
            <UploadProgress uploads={uploads} onRemove={removeUpload} className="mt-1" />
          )}

          <DialogFooter>
            <Button
              variant={hasActiveUploads ? 'outline' : 'default'}
              onClick={() => setUploadOpen(false)}
            >
              {hasActiveUploads ? 'Close (uploads continue)' : 'Done'}
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Create folder dialog ── */}
      <Dialog open={folderDlg === 'create'} onOpenChange={o => !o && setFolderDlg(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Create Folder</DialogTitle></DialogHeader>
          <Input
            placeholder="Folder name"
            value={folderInput}
            onChange={e => setFolderInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && createFolderMut.mutate(folderInput.trim())}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setFolderDlg(null)}>Cancel</Button>
            <Button disabled={!folderInput.trim() || createFolderMut.isPending}
              onClick={() => createFolderMut.mutate(folderInput.trim())}>
              <Check className="w-4 h-4 mr-1.5" /> Create
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Rename folder dialog ── */}
      <Dialog open={folderDlg === 'rename'} onOpenChange={o => !o && setFolderDlg(null)}>
        <DialogContent>
          <DialogHeader><DialogTitle>Rename Folder</DialogTitle></DialogHeader>
          <Input
            placeholder="New name"
            value={folderInput}
            onChange={e => setFolderInput(e.target.value)}
            onKeyDown={e => e.key === 'Enter' && selectedFolder && renameFolderMut.mutate({ id: selectedFolder, name: folderInput.trim() })}
          />
          <DialogFooter>
            <Button variant="outline" onClick={() => setFolderDlg(null)}>Cancel</Button>
            <Button disabled={!folderInput.trim() || renameFolderMut.isPending}
              onClick={() => selectedFolder && renameFolderMut.mutate({ id: selectedFolder, name: folderInput.trim() })}>
              <Check className="w-4 h-4 mr-1.5" /> Rename
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>

      {/* ── Delete folder dialog ── */}
      <Dialog open={folderDlg === 'delete'} onOpenChange={o => !o && setFolderDlg(null)}>
        <DialogContent>
          <DialogHeader>
            <DialogTitle>Delete Folder</DialogTitle>
            <DialogDescription>
              Delete <strong>{activeFolder?.name}</strong>? Documents inside will move to All Documents.
            </DialogDescription>
          </DialogHeader>
          <DialogFooter>
            <Button variant="outline" onClick={() => setFolderDlg(null)}>Cancel</Button>
            <Button variant="destructive" disabled={deleteFolderMut.isPending}
              onClick={() => selectedFolder && deleteFolderMut.mutate(selectedFolder)}>
              <Trash2 className="w-4 h-4 mr-1.5" /> Delete
            </Button>
          </DialogFooter>
        </DialogContent>
      </Dialog>
    </div>

    {/* ── Summarize modal ── */}
    {summarizeDoc && (
      <SummarizeModal
        docId={summarizeDoc.id}
        docName={summarizeDoc.name}
        onClose={() => setSummarizeDoc(null)}
      />
    )}
    </>
  )
}
