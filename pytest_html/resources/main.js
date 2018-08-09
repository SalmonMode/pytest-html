/* This Source Code Form is subject to the terms of the Mozilla Public
 * License, v. 2.0. If a copy of the MPL was not distributed with this file,
 * You can obtain one at http://mozilla.org/MPL/2.0/. */


shown_states = {
    "passed": true,
    "skipped": true,
    "failed": true,
    "error": true,
    "xfailed": true,
    "xpassed": true,
}

collapsed = [
    "passed",
]


function get_query_parameter(name) {
    var match = RegExp('[?&]' + name + '=([^&]*)').exec(window.location.search);
    return match && decodeURIComponent(match[1].replace(/\+/g, ' '));
}


function toggleShownState() {
    var outcome = null
    for (let o of Object.keys(shown_states)) {
        if (this.classList.contains(o)) {
            outcome = o;
            break
        }
    }
    shown_states[outcome] = !shown_states[outcome]
    updateOutcomeCountVisibility(outcome)
    updateTestVisibility()

}

function updateOutcomeCountVisibility(outcome=null) {
    var outcomes = outcome ? [outcome] : Object.keys(shown_states);

    for (let k of outcomes) {
        for (let el of document.querySelectorAll(`.${k}`)) {
            if (shown_states[k]) {
                el.classList.add("shown")
            } else {
                el.classList.remove("shown")
            }
        }
    }
}

function updateTestVisibility() {

    var true_keys = [];
    var false_keys = [];

    for (let k of Object.keys(shown_states)) {
        if (shown_states[k]) {
            true_keys.push(k);
        } else {
            false_keys.push(k)
        }
    }

    var selectorList = [];
    var filter = "";

    for (let k of true_keys){
        filter += `:not(.${k})`;
    }

    for (let k of false_keys) {
        selectorList.push(`li.${k}${filter}`);
    }
    var hideSelector = selectorList.join();

    if (hideSelector) {
        for (let el of document.querySelectorAll(hideSelector)) {
            el.classList.remove("shown");
        }
    }

    showSelectorList = [];
    for (let k of true_keys){
        showSelectorList.push(`li.${k}`);
    }

    showSelector = showSelectorList.join();

    if (showSelector) {
        for (let el of document.querySelectorAll(showSelector)) {
            el.classList.add("shown")
        }
    }
}



function init () {
    collapsed = (get_query_parameter('collapsed') || "passed").toLowerCase().split(",");

    prepareResultsHeaders();
    updateOutcomeCountVisibility();
    updateTestVisibility();

};


function toggleOpenClass() {
    this.parentNode.parentNode.classList.toggle("active");
}

function toggleOpenTrigger() {
    toggleOpen(this);
}

function toggleOpen(nodeLink) {
    if (!nodeLink.parentNode.data.children.length && !nodeLink.parentNode.data.test_results.length) {
        // nothing to show or hide
        return;
    }
    if (nodeLink.classList.contains("active")) {
        // already active so remove children after hiding them
        nodeLink.classList.toggle("active");
        nodeLink.parentNode.removeChild(nodeLink.parentNode.querySelector("div.child-containers"));
        return;
    }
    var child_containers = document.createElement("div");
    child_containers.setAttribute("class", "child-containers");

    if (nodeLink.parentNode.data.extra.length) {
        child_containers.appendChild(createExtraDiv(nodeLink.parentNode.data.extra))
    }

    if (nodeLink.parentNode.data.children.length) {
        var ul = document.createElement("ul");
        ul.setAttribute("class", "child-node-containers");
        for (var i = 0; i < nodeLink.parentNode.data.children.length; i++) {
            ul.appendChild(createNodeHeader(nodeLink.parentNode.data.children[i], !nodeLink.parentNode.odd));
        }
        child_containers.appendChild(ul);
    }

    if (nodeLink.parentNode.data.test_results.length) {
        var ul = document.createElement("ul");
        ul.setAttribute("class", "test-containers");
        for (var i = 0; i < nodeLink.parentNode.data.test_results.length; i++) {
            li = createTestDesc(nodeLink.parentNode.data.test_results[i]);

            ul.appendChild(li)
        }
        child_containers.appendChild(ul);
    }
    nodeLink.parentNode.appendChild(child_containers);
    updateOutcomeCountVisibility()
    updateTestVisibility()

    nodeLink.classList.toggle("active");

};


function prepareResultsHeaders() {
    counts = document.querySelectorAll(".summary-details .summary-result-count")

    for (let c of document.querySelectorAll(".summary-details .count-toggle-button")) {
        c.addEventListener('click', toggleShownState, false);
    }

    document.querySelector("#expand-all-button").addEventListener('click', expandAll, false);
    document.querySelector("#collapse-all-button").addEventListener('click', collapseAll, false);

    var resultsContainer = document.createElement("div");
    resultsContainer.setAttribute("class", "results");
    var resultsContainerUl = document.createElement("ul");
    resultsContainerUl.setAttribute("class", "top-container-list");

    for (var i = 0; i < resultsTree.results.length; i++) {
        resultsContainerUl.appendChild(createNodeHeader(resultsTree.results[i]));
    }
    resultsInfoDiv = document.body.querySelector(".results-info")
    resultsContainer.appendChild(resultsContainerUl)
    resultsInfoDiv.appendChild(resultsContainer)

    updateOutcomeCountVisibility()

}


function createNodeHeader(nodeDetails, odd=false) {

    var summary_container = document.createElement("li");
    summary_container.setAttribute("class", `results-summary-container ${odd ? 'odd' : 'even'}`);
    for (let k of Object.keys(nodeDetails.summary)) {
        if (nodeDetails.summary[k] > 0) {
            summary_container.classList.add(k);
        }
    }
    summary_container.data = nodeDetails
    summary_container.innerHTML = `
        <div class="results-summary-container-header">
            <div class="node-level-description">
                    <div class="name">${nodeDetails.name}</div>
                    <div class="params">${nodeDetails.param_description ? "[" + nodeDetails.param_description + "]" : ""}</div>
            </div>
            <div class="results-summary-numbers-wrapper">
                <div class="node-duration">Duration: ${nodeDetails.duration}s</div>
                <div class="results-summary-numbers">
                    <div class="summary-result-count passed" title="Passes">${nodeDetails.summary.passed}</div>
                    <div class="summary-result-count skipped" title="Skips">${nodeDetails.summary.skipped}</div>
                    <div class="summary-result-count failed" title="Failures">${nodeDetails.summary.failed}</div>
                    <div class="summary-result-count error" title="Errors">${nodeDetails.summary.error}</div>
                    <div class="summary-result-count xfailed" title="Expected failures">${nodeDetails.summary.xfailed}</div>
                    <div class="summary-result-count xpassed" title="Unexpected passes">${nodeDetails.summary.xpassed}</div>
                </div>
            </div>
        </div>
    `
    summary_container.odd = odd
    summary_container.querySelector("div.results-summary-container-header").addEventListener('click', toggleOpenTrigger, false);

    return summary_container
}


function createTestDesc(testDetails) {

    var testDesc = document.createElement("li");
    testDesc.setAttribute("class", `test-result ${testDetails.outcome.toLowerCase()}`);
    testDesc.innerHTML = `
        <div class="result-wrapper">
            <div class="test-info-wrapper">
                <div class="outcome">${testDetails.outcome.toUpperCase()}</div>
                <div class="test-description">
                    <div class="name">${testDetails.name}</div>
                    <div class="params">${testDetails.param_description ? "[" + testDetails.param_description + "]" : ""}</div>
                </div>
                <div class="nodeid tooltip">nodeid<span class="tooltiptext">${testDetails.nodeid}</span></div>
                <div class="location tooltip">location<span class="tooltiptext">${testDetails.location}</span></div>
                <button class="toggle-log"></button>
            </div>
            <div class="duration">Duration: ${testDetails.duration}s</div>
        </div>
        ${testDetails.log}
    `
    if (testDetails.extra.length) {
        extraDiv = createExtraDiv(testDetails.extra);
        logDiv = testDesc.querySelector(".log")
        testDesc.insertBefore(extraDiv, logDiv);
    }
    testDesc.querySelector("button.toggle-log").addEventListener('click', toggleOpenClass, false);

    if (!collapsed.includes(testDetails.outcome.toLowerCase())) {
        testDesc.querySelector(".result-wrapper").classList.add("active")
    }

    return testDesc
}


function expandAll() {
    while (document.querySelectorAll("li.results-summary-container .results-summary-container-header:not(.active)").length > 0) {
        toggleOpen(document.querySelector("li.results-summary-container .results-summary-container-header:not(.active)"));
    }
}

function collapseAll() {
    while (document.querySelectorAll(".top-container-list > li.results-summary-container .results-summary-container-header.active").length > 0) {
        toggleOpen(document.querySelector(".top-container-list > li.results-summary-container .results-summary-container-header.active"));
    }
}


function createExtraDiv(extras) {
    var imagesDiv = document.createElement("div");
    imagesDiv.classList.add("extra-image-previews-wrapper");
    imagesDiv.images = [];
    var othersDiv = document.createElement("div");
    othersDiv.classList.add("extra-others");

    var imageIndex = 0;
    for (let ex of extras) {
        if (ex.format == "image") {
            imagesDiv.appendChild(createExtraImagePreview(ex, imageIndex));
            // add references for use by slideshow
            imagesDiv.images.push(ex);
            imageIndex += 1;
        } else {
            switch(ex.format) {
                case "text":
                    othersDiv.appendChild(createExtraText(ex));
                    break;
                case "json":
                    othersDiv.appendChild(createExtraJson(ex));
                    break;
                case "link":
                    othersDiv.appendChild(createExtraLink(ex));
                    break;
                case "html":
                    othersDiv.appendChild(createExtraHtml(ex));
                    break;
                default:
                    break;
            }
        }
    }

    var extrasDiv = document.createElement("div");
    extrasDiv.classList.add("extras");
    if (imagesDiv.childNodes.length){
        extrasDiv.appendChild(imagesDiv);
    }
    if (othersDiv.childNodes.length){
        extrasDiv.appendChild(othersDiv);
    }
    extrasDiv.appendChild(othersDiv);
    return extrasDiv
}

function createExtraImagePreview(imageDetails, imageIndex) {
    var imagePreviewDiv = document.createElement("div");
    imagePreviewDiv.classList.add("extra");
    imagePreviewDiv.classList.add("extra-image-preview");
    previewImageWrapper = document.createElement("div");
    previewImageWrapper.classList.add("preview-image-wrapper");
    var img = document.createElement("img");
    img.setAttribute("src", imageDetails.content);
    img.setAttribute("alt", imageDetails.name);
    img.setAttribute("title", imageDetails.name);
    imagePreviewDiv.addEventListener('click', showSlideshow, false);
    imagePreviewDiv.imageIndex = imageIndex;
    previewImageWrapper.appendChild(img);
    imagePreviewDiv.appendChild(previewImageWrapper);
    return imagePreviewDiv;
}



function createExtraText(textDetails) {
    var textDiv = document.createElement("div");
    textDiv.classList.add("extra");
    textDiv.classList.add("extra-text");
    var contentDiv = document.createElement("div");
    contentDiv.classList.add("content");
    contentDiv.innerHTML = textDetails.content
    textDiv.appendChild(contentDiv);
    return textDiv;
}

function createExtraText(textDetails) {
    var textDiv = document.createElement("div");
    textDiv.classList.add("extra");
    textDiv.classList.add("extra-text");
    var contentDiv = document.createElement("div");
    contentDiv.classList.add("content");
    var pre = document.createElement("pre");
    pre.innerHTML = textDetails.content
    contentDiv.appendChild(pre);
    textDiv.appendChild(contentDiv);
    return textDiv;
}

function createExtraJson(jsonDetails) {
    var jsonDiv = document.createElement("div");
    jsonDiv.classList.add("extra");
    jsonDiv.classList.add("extra-json");
    var contentDiv = document.createElement("div");
    contentDiv.classList.add("content");
    var pre = document.createElement("pre");
    pre.innerHTML = JSON.stringify(jsonDetails.content, null, 4);
    contentDiv.appendChild(pre);
    jsonDiv.appendChild(contentDiv);
    return jsonDiv;
}

function createExtraLink(linkDetails) {
    var linkDiv = document.createElement("div");
    linkDiv.classList.add("extra");
    linkDiv.classList.add("extra-link");
    var contentDiv = document.createElement("div");
    contentDiv.classList.add("content");
    var a = document.createElement("a");
    a.setAttribute("href", linkDetails.content);
    contentDiv.appendChild(a);
    linkDiv.appendChild(contentDiv);
    return linkDiv;
}

function createExtraHtml(htmlDetails) {
    var htmlDiv = document.createElement("div");
    htmlDiv.classList.add("extra");
    htmlDiv.classList.add("extra-html");
    var contentDiv = document.createElement("div");
    contentDiv.classList.add("content");
    contentDiv.innerHTML = htmlDetails.content;
    htmlDiv.appendChild(contentDiv);
    return htmlDiv;
}




function showSlideshow() {
    var startIndex = this.imageIndex;
    var slideshowContainer = document.createElement("div");
    slideshowContainer.setAttribute("class", "slideshow-wrapper");
    var backdrop = document.createElement("div");
    backdrop.setAttribute("class", "backdrop");
    var slideshowCloseButton = document.createElement("div");
    slideshowCloseButton.setAttribute("class", "slideshow-close-button");
    slideshowCloseButton.addEventListener('click', closeSlideshow, false);

    backdrop.addEventListener('click', closeSlideshow, false);
    slideshowContainer.appendChild(backdrop);

    var slideshowImageViewer = document.createElement("div");
    slideshowImageViewer.setAttribute("class", "slideshow-image-viewer");


    var thumbnailContainer = document.createElement("div");
    thumbnailContainer.classList.add("thumbnail-container");

    var images = this.parentNode.images;
    for (var i = 0; i < images.length; i++) {
        let imageDetails = images[i];

        // create slide
        let slideDiv = document.createElement("div");
        slideDiv.classList.add("slideshow-image");

        let num = document.createElement("div");
        num.classList.add("slideshow-number");
        num.innerText = `${i + 1} / ${images.length}`;

        let slideImg = document.createElement("img");
        slideImg.setAttribute("src", imageDetails.content);
        slideImg.setAttribute("alt", imageDetails.name);
        slideImg.setAttribute("title", imageDetails.name);

        slideDiv.appendChild(num);
        slideDiv.appendChild(slideImg);
        slideshowImageViewer.appendChild(slideDiv);

        // create thumbnail
        let thumbImg = document.createElement("img");
        thumbImg.setAttribute("src", imageDetails.content);
        thumbImg.setAttribute("onclick", `switchToSlide(${i})`);
        thumbImg.setAttribute("alt", imageDetails.name);
        thumbImg.setAttribute("title", imageDetails.name);
        thumbImg.classList.add("thumbnail-image");

        thumbnailContainer.appendChild(thumbImg);
    }

    let slideshowImageDetails = document.createElement("div");
    slideshowImageDetails.classList.add("slideshow-image-details");

    var prevButton = document.createElement("div");
    prevButton.classList.add("prev");
    prevButton.addEventListener("click", moveToPrevSlide, false);
    var nextButton = document.createElement("div");
    nextButton.classList.add("next");
    nextButton.addEventListener("click", moveToNextSlide, false);

    slideshowImageViewer.appendChild(prevButton);
    slideshowImageViewer.appendChild(nextButton);

    var slideshowImageViewerContainer = document.createElement("div");
    slideshowImageViewerContainer.classList.add("slideshow-image-viewer-container");
    slideshowImageDetails.appendChild(slideshowImageViewer);
    slideshowImageViewerContainer.appendChild(slideshowImageDetails);
    slideshowImageViewerContainer.appendChild(slideshowCloseButton);

    var captionContainer = document.createElement("div");
    captionContainer.classList.add("caption-container");

    var captionP = document.createElement("p");
    captionP.setAttribute("id", "caption");

    captionContainer.appendChild(captionP);

    slideshowImageViewerContainer.appendChild(captionContainer);
    slideshowImageViewerContainer.appendChild(thumbnailContainer);
    slideshowContainer.appendChild(slideshowImageViewerContainer);
    slideshowContainer.currentSlide = startIndex;

    document.body.appendChild(slideshowContainer);

    switchToSlide(startIndex);
}


function closeSlideshow() {
    document.body.removeChild(document.body.querySelector(".slideshow-wrapper"));
}


// Next/previous controls
function moveToNextSlide() {
    shiftSlides(1);
}
function moveToPrevSlide() {
    shiftSlides(-1);
}

document.onkeydown = checkKey;

function checkKey(e) {

    e = e || window.event;

    if (document.body.querySelector(".slideshow-wrapper")) {
        if (e.keyCode == '37') {
           // left arrow
           moveToPrevSlide();
        }else if (e.keyCode == '39') {
           // right arrow
           moveToNextSlide();
       }else if (e.keyCode == '27') {
           // ESC
           closeSlideshow();
        }
    }

}


function shiftSlides(n) {
    var slideshowContainer = document.querySelector(".slideshow-wrapper");
    var slideIndex = slideshowContainer.currentSlide;
    switchToSlide(slideIndex += n);
}

// Thumbnail image controls
function switchToSlide(n) {
    var slideshowContainer = document.querySelector(".slideshow-wrapper");
    var slides = document.getElementsByClassName("slideshow-image");
    var thumbnails = document.getElementsByClassName("thumbnail-image");
    var slideIndex;
    if (n >= slides.length) {
        slideIndex = 0;
    } else if (n < 0) {
        slideIndex = slides.length - 1;
    } else {
        slideIndex = n;
    }

    slideshowContainer.currentSlide = slideIndex

    for (i = 0; i < slides.length; i++) {
        if (i != slideshowContainer.currentSlide){
            slides[i].classList.remove("active");
            thumbnails[i].classList.remove("active");
        } else {
            slides[i].classList.add("active");
            thumbnails[i].classList.add("active");
            thumbnails[i].scrollIntoView()
        }
    }
    var captionText = document.getElementById("caption");
    captionText.innerHTML = thumbnails[slideIndex].alt;

}
