// SPDX-License-Identifier: AGPL-3.0-only
import { AfterViewInit, Component, ElementRef, OnDestroy, ViewChild } from '@angular/core';
declare global {
  interface Window {
    OpenOfficeHarness?: {WordRain: {mount(canvas: HTMLCanvasElement): {stop(): void}}};
  }
}
@Component({
  selector: 'app-rain',
  template: '<canvas #rain aria-hidden="true"></canvas>',
  styles: ':host,canvas{position:absolute;inset:0;width:100%;height:100%;pointer-events:none}',
})
export class Rain implements AfterViewInit, OnDestroy {
  @ViewChild('rain') canvas!: ElementRef<HTMLCanvasElement>;
  private animation?: {stop(): void};
  ngAfterViewInit(): void {
    this.animation = window.OpenOfficeHarness?.WordRain.mount(this.canvas.nativeElement);
  }
  ngOnDestroy(): void { this.animation?.stop(); }
}
