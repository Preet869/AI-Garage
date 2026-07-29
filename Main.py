import cv2
import ollama 
from ultralytics import YOLO

object_detection = YOLO("yolov8n.pt")

camera = cv2.VideoCapture(0)

last_y_position = None
