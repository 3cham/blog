package main

import (
	"bytes"
	"io/ioutil"
	"net/http"
	"path/filepath"
	"strconv"
	"strings"
	"sync"

	"github.com/kjk/u"
)

var redirects = map[string]string{
	"/index.html":                                   "/",
	"/blog":                                         "/",
	"/blog/":                                        "/",
	"/feed/rss2/atom.xml":                           "/atom.xml",
	"/feed/rss2/":                                   "/atom.xml",
	"/feed/rss2":                                    "/atom.xml",
	"/feed/":                                        "/atom.xml",
	"/feed":                                         "/atom.xml",
	"/feedburner.xml":                               "/atom.xml",
}

var articleRedirects = make(map[string]string)
var articleRedirectsMutex sync.Mutex

func readRedirects() {
	fname := filepath.Join("article_redirects.txt")
	d, err := ioutil.ReadFile(fname)
	if err != nil {
		return
	}
	lines := bytes.Split(d, []byte{'\n'})
	for _, l := range lines {
		if 0 == len(l) {
			continue
		}
		parts := strings.Split(string(l), "|")
		u.PanicIf(len(parts) != 2, "malformed article_redirects.txt, len(parts) = %d (!2)", len(parts))
		idStr := parts[0]
		url := strings.TrimSpace(parts[1])
		idNum, err := strconv.Atoi(idStr)
		u.PanicIfErr(err, "malformed line in article_redirects.txt. Line:\n%s\n", l)
		id := u.EncodeBase64(idNum)
		a := store.GetArticleByID(id)
		if a != nil {
			articleRedirects[url] = id
			continue
		}
		//fmt.Printf("skipping redirect '%s' because article with id %d no longer present\n", string(l), id)
	}
	logger.Noticef("loaded %d article redirects", len(articleRedirects))
}

// return -1 if there's no redirect for this urls
func getRedirectArticleID(url string) string {
	url = url[1:] // remove '/' from the beginning
	articleRedirectsMutex.Lock()
	defer articleRedirectsMutex.Unlock()
	return articleRedirects[url]
}

func redirectIfNeeded(w http.ResponseWriter, r *http.Request) bool {
	uri := r.URL.Path
	//logger.Noticef("redirectIfNeeded(): %q", uri)

	if redirURL, ok := redirects[uri]; ok {
		//logger.Noticef("Redirecting %q => %q", url, redirUrl)
		http.Redirect(w, r, redirURL, 302)
		return true
	}

	redirectArticleID := getRedirectArticleID(uri)
	if redirectArticleID == "" {
		return false
	}
	article := store.GetArticleByID(redirectArticleID)
	if article != nil {
		redirURL := "/" + article.Permalink()
		//logger.Noticef("Redirecting %q => %q", url, redirUrl)
		http.Redirect(w, r, redirURL, 302)
		return true
	}

	return false
}