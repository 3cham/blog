package main

import (
	"fmt"
	"log"
	"net/http"
	"sync"
	"time"

	"github.com/fsnotify/fsnotify"
	"github.com/gorilla/websocket"
)

var (
	mu sync.Mutex
)

func watchChanges(watcher *fsnotify.Watcher, close chan struct{}, notify chan struct{}) {
	for {
		select {
		case <-close:
			log.Printf("watchChange: stopped watching\n")
			return
		case err := <-watcher.Errors:
			if err != nil {
				log.Println("error:", err)
			}
		case ev := <-watcher.Events:
			path := ev.Name
			if isTmpFile(path) {
				continue
			}
			log.Printf("notifyFileChanges: notify about %s, event: %s\n", path, ev.String())
			if ev.Op == fsnotify.Chmod {
				log.Printf("skipping CHMOD event")
				continue
			}
			// note: this is unsafe but only done in dev mode
			loadArticles()
			notify <- struct{}{}
		}
	}
}

func startBlogPostsWatcher() *fsnotify.Watcher {
	if flgProduction {
		return nil
	}
	watcher, err := fsnotify.NewWatcher()
	if err != nil {
		fmt.Printf("fsnotify.NewWather() failed with %s\n", err)
		watcher.Close()
		return nil
	}

	dirs := store.GetDirsToWatch()
	dirs = append(dirs, "articles")
	for _, dir := range dirs {
		err = watcher.Add(dir)
		if err != nil {
			fmt.Printf("watcher.Add() for %s failed with %s\n", dir, err)
			watcher.Close()
			return nil
		}
	}
	return watcher
}

const (
	// Time allowed to write the file to the client.
	writeWait = 10 * time.Second

	// Time allowed to read the next pong message from the client.
	pongWait = 60 * time.Second

	// Send pings to client with this period. Must be less than pongWait.
	pingPeriod = (pongWait * 9) / 10
)

func wsWriter(ws *websocket.Conn, wsChan chan struct{}, chClose chan struct{}) {
	ticker := time.NewTicker(pingPeriod)
	for {
		select {
		case <-ticker.C:
			log.Print("sending ws ping")
			if err := ws.WriteMessage(websocket.PingMessage, []byte{}); err != nil {
				log.Print(err)
				return
			}
		case <-wsChan:
			err := ws.WriteMessage(websocket.TextMessage, []byte{})
			if err != nil {
				log.Printf("wsWrite: ws.WriteMessage failed with '%s'\n", err)
				return
			}
		case <-chClose:
			return
		}
	}
}

// serveWs receives a file name from a websocket client and relays to it
// all the notifications about changes to this file.
func serveWs(w http.ResponseWriter, r *http.Request) {
	log.Printf("serveWs: new connection\n")

	var upgrader = websocket.Upgrader{
		ReadBufferSize:  1024,
		WriteBufferSize: 1024,
	}
	ws, err := upgrader.Upgrade(w, r, nil)
	if err != nil {
		if _, ok := err.(websocket.HandshakeError); !ok {
			log.Printf("serveWs: upgrader.Upgrade() failed with '%s'\n", err)
		}
		return
	}

	defer ws.Close()
	ws.SetReadLimit(512)
	ws.SetReadDeadline(time.Now().Add(pongWait))
	ws.SetPongHandler(func(string) error { ws.SetReadDeadline(time.Now().Add(pongWait)); return nil })

	wsChan := make(chan struct{})
	close := make(chan struct{})

	watcher := startBlogPostsWatcher()
	if watcher != nil {
		defer watcher.Close()
		go watchChanges(watcher, close, wsChan)
	}

	go wsWriter(ws, wsChan, close)
	for {
		msgType, p, err := ws.ReadMessage()
		if err != nil {
			log.Printf("serveWs: ws.ReadMessage() failed with '%s'\n", err)
			break
		}
		log.Printf("Got ws msg type: %d s: '%s'\n", msgType, string(p))
		uri := string(p)
		articleInfo := articleInfoFromURL(uri)
		if articleInfo == nil {
			log.Printf("serveWs: didn't find article for uri %s\n", uri)
			continue
		}
	}
	close <- struct{}{}

}
