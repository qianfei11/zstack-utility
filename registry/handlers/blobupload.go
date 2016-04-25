package handlers

import (
	"crypto/sha1"
	"encoding/hex"
	"errors"
	"fmt"
	"github.com/docker/distribution/context"
	"image-store/registry/api/errcode"
	"image-store/registry/api/v1"
	"io"
	"net/http"
	"strings"
)

// The maximum chunk size is 8 MiB
const MaxChunkSize = 8 * 1024 * 1024

var ErrorUploadIncomplete = errors.New("upload incomplete")
var ErrorInvalidChunkSize = errors.New("invalid chunk size")

// POST /v1/{name}/blob-upload/
// {
//   "digest": "...",
// }
//
// Returns HTTP Accepted, with a Location header to be PATCH with.
func PrepareBlobUpload(ctx context.Context, w http.ResponseWriter, r *http.Request) {
	n, info, s := GetUploadInfoAndSearcher(ctx, w, r)
	if info == nil {
		WriteHttpError(w, errors.New("invalid digest"), http.StatusBadRequest)
		return
	}

	if s == nil {
		return
	}

	loc, err := s.PrepareBlobUpload(ctx, n, info)
	if err != nil {
		switch err.(type) {
		case errcode.ConflictError, *errcode.ConflictError:
			WriteHttpError(w, err, http.StatusConflict)
		default:
			WriteHttpError(w, err, http.StatusBadRequest)
		}

		return
	}

	w.Header().Set("Location", loc)
	w.WriteHeader(http.StatusAccepted)
}

// GET /v1/{name}/blobs/uploads/{uuid}
func GetUploadProgress(ctx context.Context, w http.ResponseWriter, r *http.Request) {
	n, uu, s := GetUploadQueryArgAndSearcher(ctx, w, r)
	if s == nil {
		return
	}

	sz, err := s.GetUploadedSize(ctx, n, uu)
	if err != nil {
		WriteHttpError(w, err, http.StatusBadRequest)
		return
	}

	w.Header().Set("Content-Range", fmt.Sprintf("bytes 0-%d", sz-1))
	w.WriteHeader(http.StatusNoContent)
	return
}

func writeChunk(dest io.Writer, r *http.Request) error {
	length := r.ContentLength
	if length < 0 || length > MaxChunkSize {
		return ErrorInvalidChunkSize
	}

	hashsum := strings.TrimSpace(r.Header.Get(v1.HnChunkHash))
	if hashsum == "" {
		return errors.New("missing chunk hash from header")
	}

	hasher := sha1.New()
	bodyReader := io.TeeReader(io.LimitReader(r.Body, length), hasher)

	// TODO validate hash before copy to destination
	sz, err := io.Copy(dest, bodyReader)
	if err != nil {
		return err
	}

	// check size
	if sz != r.ContentLength {
		return ErrorUploadIncomplete
	}

	if strings.EqualFold(hex.EncodeToString(hasher.Sum(nil)), hashsum) {
		return nil
	}

	return errors.New("chunk corrupted - hash mismatch")
}

// PATCH /v1/{name}/blobs/uploads/{uuid}
// Content-Length: <size of chunk>
// Range: <start of range>-<end of range>
func UploadBlobChunk(ctx context.Context, w http.ResponseWriter, r *http.Request) {
	n, uu, s := GetUploadQueryArgAndSearcher(ctx, w, r)
	if s == nil {
		return
	}

	wr, err := s.GetChunkWriter(ctx, n, uu)
	if err != nil {
		WriteHttpError(w, err, http.StatusBadRequest)
		return
	}

	defer wr.Close()

	if err = writeChunk(wr, r); err != nil {
		WriteHttpError(w, ErrorUploadIncomplete, http.StatusBadRequest)
		return
	}

	return
}

// PUT /v1/{name}/blobs/uploads/{uuid}
// Content-Length: <size of chunk>
// Range: <start of range>-<end of range>
// PUT the last chunk
func CompleteUpload(ctx context.Context, w http.ResponseWriter, r *http.Request) {
	n, uu, s := GetUploadQueryArgAndSearcher(ctx, w, r)
	if s == nil {
		return
	}

	wr, err := s.GetChunkWriter(ctx, n, uu)
	if err != nil {
		WriteHttpError(w, err, http.StatusBadRequest)
		return
	}

	defer wr.Close()

	if err = writeChunk(wr, r); err != nil {
		WriteHttpError(w, ErrorUploadIncomplete, http.StatusBadRequest)
		return
	}

	// Complete upload.
	if err = s.CompleteUpload(ctx, n, uu); err != nil {
		WriteHttpError(w, err, http.StatusBadRequest)
		return
	}

	return
}

// DELETE /v1/{name}/blobs/uploads/{uuid}
func CancelUpload(ctx context.Context, w http.ResponseWriter, r *http.Request) {
	n, uu, s := GetUploadQueryArgAndSearcher(ctx, w, r)
	if s == nil {
		return
	}

	if err := s.CancelUpload(ctx, n, uu); err != nil {
		WriteHttpError(w, err, http.StatusBadRequest)
		return
	}

	w.WriteHeader(http.StatusAccepted)
	return
}
