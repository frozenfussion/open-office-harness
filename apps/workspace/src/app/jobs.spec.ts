// SPDX-License-Identifier: AGPL-3.0-only
import { TestBed } from '@angular/core/testing';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { Api, ApiError, Job } from './api';
import { Jobs, jobLabel, reconnectDelay } from './jobs';
import { JobCard } from './job-card';
import { SseParser } from './sse';
const job: Job = {job_id: '12345678-1234-1234-1234-123456789012', skill: 'slides', title: 'Presentation (.pptx)', label: 'The water cycle', status: 'queued'};
describe('Jobs', () => {
  afterEach(() => { TestBed.resetTestingModule(); vi.restoreAllMocks(); vi.useRealTimers(); });
  it('parses fragmented jobs events and ignores keep-alive comments', () => {
    const receive = vi.fn(); const parser = new SseParser(receive);
    parser.push(': keep-alive\r\n\r\ndata: {"type":"job.completed",');
    parser.push('"correlation_id":"job","skill":"slides","output":null,"error":null}\r\n\r\n');
    expect(receive).toHaveBeenCalledOnce(); expect(receive.mock.calls[0][0].type).toBe('job.completed');
  });
  it('backs off failed connections after 1, 2, 5 and 10 seconds', async () => {
    vi.useFakeTimers();
    expect([0,1,2,3,4].map(reconnectDelay)).toEqual([1000,2000,5000,10000,10000]);
    const events = vi.fn().mockRejectedValue(new Error('Connection failed'));
    TestBed.configureTestingModule({providers: [{provide: Api, useValue: {events}}]});
    const store = TestBed.inject(Jobs); store.start();
    await vi.advanceTimersByTimeAsync(0); expect(events).toHaveBeenCalledTimes(1);
    for (const [index, delay] of [1000,2000,5000,10000].entries()) {
      await vi.advanceTimersByTimeAsync(delay - 1); expect(events).toHaveBeenCalledTimes(index + 1);
      await vi.advanceTimersByTimeAsync(1); expect(events).toHaveBeenCalledTimes(index + 2);
    }
    store.stop();
  });
  it('reloads on connection and waits one second again after reconnecting then dropping', async () => {
    vi.useFakeTimers();
    const jobs = vi.fn().mockResolvedValue([job]);
    const events = vi.fn(async (_signal, connected) => { await connected(); });
    TestBed.configureTestingModule({providers: [{provide: Api, useValue: {jobs, events}}]});
    const store = TestBed.inject(Jobs); store.start();
    await vi.advanceTimersByTimeAsync(0); expect(jobs).toHaveBeenCalledTimes(1);
    await vi.advanceTimersByTimeAsync(1000); expect(jobs).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(999); expect(jobs).toHaveBeenCalledTimes(2);
    await vi.advanceTimersByTimeAsync(1); expect(jobs).toHaveBeenCalledTimes(3);
    store.stop(); await vi.advanceTimersByTimeAsync(10000);
    expect(events).toHaveBeenCalledTimes(3); expect(store.rows()).toEqual([]);
  });
  it('updates job states, preserves newer events during a reload, and handles rejection', async () => {
    let resolve!: (rows: Job[]) => void;
    TestBed.configureTestingModule({providers: [{provide: Api, useValue: {jobs: () => new Promise<Job[]>(done => resolve = done)}}]});
    const store = TestBed.inject(Jobs); store.add(job);
    const pending = store.reload();
    store.receive({type:'job.completed',correlation_id:job.job_id,skill:'slides',output:{file_key:'outputs/test.pptx',mime:'test',summary:'Ready'},error:null});
    resolve([job]); await pending; expect(store.rows()[0].status).toBe('completed');
    store.receive({type:'job.failed',correlation_id:job.job_id,skill:'slides',output:null,error:{code:'approval_rejected',message:'Not approved'}});
    expect(store.rows()[0].status).toBe('completed');
    store.add({...job, job_id: 'second'});
    store.receive({type:'job.failed',correlation_id:'second',skill:'slides',output:null,error:{code:'approval_rejected',message:'Not approved'}});
    expect(store.rows()[0].status).toBe('rejected');
    expect(['awaiting_approval','queued','completed','failed','rejected'].map(status => jobLabel(status as Job['status'])))
      .toEqual(['Waiting for approval','Queued','Ready','Failed','Not approved']);
  });
  it('keeps a newer Queued event over an older approval snapshot', async () => {
    let resolve!: (rows: Job[]) => void;
    TestBed.configureTestingModule({providers: [{provide: Api, useValue: {jobs: () => new Promise<Job[]>(done => resolve = done)}}]});
    const store = TestBed.inject(Jobs); store.add({...job, status: 'awaiting_approval'});
    const pending = store.reload();
    store.receive({type: 'job.queued', correlation_id: job.job_id, skill: 'slides', output: null, error: null});
    resolve([{...job, status: 'awaiting_approval'}]); await pending;
    expect(store.rows()[0].status).toBe('queued');
  });
  it.each(['event', 'reload', 'add', 'overlapping reload'])('revives only worker_gave_up jobs via %s', async source => {
    let resolve!: (rows: Job[]) => void;
    TestBed.configureTestingModule({providers: [{provide: Api, useValue: {jobs: () => new Promise<Job[]>(done => resolve = done)}}]});
    const store = TestBed.inject(Jobs);
    for (const [status, code, expected] of [
      ['failed', 'worker_gave_up', 'completed'], ['failed', 'other', 'failed'], ['rejected', 'approval_rejected', 'rejected'],
    ] as const) {
      store.stop(); store.add({...job, status, error: {code, message: 'Test failure'}});
      const completed: Job = {...job, status: 'completed', output: {file_key: 'outputs/slides/test.pptx', mime: 'test', summary: 'Ready'}, error: null};
      if (source === 'event') store.receive({type:'job.completed',correlation_id:job.job_id,skill:'slides',output:completed.output,error:null});
      else if (source === 'add') store.add(completed);
      else {
        const pending = store.reload();
        if (source === 'overlapping reload') store.add({...job, status, error: {code, message: 'Test failure'}});
        resolve([completed]); await pending;
      }
      expect(store.rows()[0].status).toBe(expected);
      if (expected === 'completed') expect(store.rows()[0].error).toBeNull();
    }
  });
  it('stops retrying when access is refused', async () => {
    vi.useFakeTimers(); const events = vi.fn().mockRejectedValue(new ApiError(403,'Access removed'));
    TestBed.configureTestingModule({providers:[{provide:Api,useValue:{events}}]});
    const store=TestBed.inject(Jobs); store.start(); await vi.advanceTimersByTimeAsync(20000);
    expect(events).toHaveBeenCalledOnce(); expect(store.notice()).toBe('Access removed'); store.stop();
  });
  it('renders a chat job card with request ID, copies the full ID, and downloads only Ready jobs', async () => {
    const download=vi.fn().mockResolvedValue(undefined); const copy=vi.fn().mockResolvedValue(undefined);
    Object.defineProperty(navigator,'clipboard',{configurable:true,value:{writeText:copy}});
    TestBed.configureTestingModule({imports:[JobCard],providers:[{provide:Api,useValue:{download}}]});
    const view=TestBed.createComponent(JobCard); view.componentRef.setInput('job',job);view.detectChanges();
    expect(view.nativeElement.textContent).toContain('Request ID 12345678');
    expect(view.nativeElement.textContent).toContain('The water cycle');
    expect(view.nativeElement.textContent).not.toContain('Download');
    await view.componentInstance.copy();expect(copy).toHaveBeenCalledWith(job.job_id);
    view.componentRef.setInput('job',{...job,status:'completed'});view.detectChanges();
    await view.componentInstance.download();expect(download).toHaveBeenCalledWith({...job,status:'completed'});
    view.componentRef.setInput('job',{...job,status:'failed',error:{code:'worker_gave_up',message:'The job failed.'}});view.detectChanges();
    expect(view.nativeElement.querySelector('[role="alert"]').textContent).toBe('The job failed.');
  });
});
