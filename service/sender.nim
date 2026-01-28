import asyncdispatch, os, strformat
import ssh2
from libssh2 import
  libssh2_sftp_init,
  libssh2_sftp_shutdown,
  libssh2_sftp_open,
  libssh2_sftp_close,
  libssh2_sftp_write,
  LIBSSH2_FXF_WRITE,
  LIBSSH2_FXF_CREAT,
  LIBSSH2_FXF_TRUNC,
  LIBSSH2_SFTP_S_IRUSR,
  LIBSSH2_SFTP_S_IWUSR

proc uploadFile(
  ssh: SSHClient,
  localPath: string,
  remotePath: string
) =
  let sftp = libssh2_sftp_init(ssh.session)
  if sftp.isNil:
    raise newException(SSHException, "Failed to init SFTP session")

  let handle = libssh2_sftp_open(
    sftp,
    remotePath,
    LIBSSH2_FXF_WRITE or LIBSSH2_FXF_CREAT or LIBSSH2_FXF_TRUNC,
    LIBSSH2_SFTP_S_IRUSR or LIBSSH2_SFTP_S_IWUSR
  )

  if handle.isNil:
    libssh2_sftp_shutdown(sftp)
    raise newException(SSHException, &"Failed to open remote file {remotePath}")

  let data = readFile(localPath)
  discard libssh2_sftp_write(handle, data.cstring, data.len)

  discard libssh2_sftp_close(handle)
  discard libssh2_sftp_shutdown(sftp)

proc sendChunk(
  ssh: SSHClient,
  remoteDir: string,
  files: seq[string]
) =
  for localFile in files:
    let fileName = extractFilename(localFile)
    let remotePath = remoteDir / fileName

    echo &"Uploading {localFile} → {remotePath}"
    uploadFile(ssh, localFile, remotePath)

proc main() {.async.} =
  if paramCount() < 2:
    quit("Usage: sender <remote_dir> <file1> <file2> ...")

  let remoteDir = paramStr(1)
  let files = paramStrs()[1..^1]

  let client = newSSHClient()
  try:
    await client.connect(
      hostname = "example.com",
      username = "user",
      password = "pass"
    )

    sendChunk(client, remoteDir, files)

  finally:
    client.disconnect()

waitFor main()